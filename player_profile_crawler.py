#!/usr/bin/env python3
"""
玩家个人主页资料爬虫
用于爬取玩家的详细个人信息、头衔、成就等
"""

import requests
from bs4 import BeautifulSoup
import sqlite3
import time
import os
import logging
import sys
import signal
import threading
from datetime import datetime, timedelta
import re
import json
import argparse
from threading import Lock
import hashlib
from logging.handlers import RotatingFileHandler
import queue
from concurrent.futures import ThreadPoolExecutor, as_completed
import random
import pprint

# 复用现有的数据库管理器和配置
from malody_rankings import DatabaseManager, init_database, stop_requested, stop_lock, COOKIES, HEADERS

# 配置日志
def setup_detailed_logging(log_level=logging.INFO, log_file=None):
    """设置详细的日志配置"""
    
    # 创建logs目录
    if not os.path.exists('logs'):
        os.makedirs('logs')
    
    # 默认日志文件
    if log_file is None:
        log_file = f"logs/player_profile_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    
    # 创建logger
    logger = logging.getLogger()
    logger.setLevel(log_level)
    
    # 清除现有的handler
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
    
    # 详细的日志格式
    detailed_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(funcName)s - %(message)s'
    )
    
    # 简化的控制台格式
    console_formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s'
    )
    
    # 文件handler - 滚动日志，每个文件10MB，保留5个备份
    file_handler = RotatingFileHandler(
        log_file, 
        maxBytes=10*1024*1024,  # 10MB
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setFormatter(detailed_formatter)
    file_handler.setLevel(log_level)
    
    # 控制台handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(console_formatter)
    console_handler.setLevel(log_level)
    
    # 添加handler
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    logger.info("=" * 80)
    logger.info("玩家个人主页爬虫启动")
    logger.info("日志文件: %s", log_file)
    logger.info("日志级别: %s", logging.getLevelName(log_level))
    logger.info("=" * 80)
    
    return logger

# Malody API配置
BASE_URL = "https://m.mugzone.net"
PLAYER_PROFILE_URL = BASE_URL + "/accounts/user/{uid}"

# 全局变量
player_queue = queue.Queue()
crawl_progress = {}
progress_lock = Lock()

class PlayerProfileCrawler:
    def __init__(self, session=None):
        self.logger = logging.getLogger('PlayerProfileCrawler')
        
        if session is None:
            # 创建新的session并复用认证配置
            self.session = requests.Session()
            self.session.cookies.update(COOKIES)
            
            # 使用与主爬虫完全相同的headers
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Referer": "https://m.mugzone.net/",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
                "Accept-Encoding": "gzip, deflate, br",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1",
            }
            
            # 添加CSRF token到headers
            if 'csrftoken' in COOKIES:
                headers['X-CSRFToken'] = COOKIES['csrftoken']
                headers['X-CSRF-Token'] = COOKIES['csrftoken']
                headers['X-CSRFTOKEN'] = COOKIES['csrftoken']
            
            self.session.headers.update(headers)
            
            # 使用与主爬虫相同的适配器配置
            self.session.mount('https://', requests.adapters.HTTPAdapter(
                max_retries=3,
                pool_connections=10,
                pool_maxsize=10
            ))
        else:
            self.session = session
            
        self.db_manager = DatabaseManager()
        # 初始化数据库时暂时禁用外键约束，避免因achievement_catalog缺失导致失败
        self.db_manager.get_connection().execute('PRAGMA foreign_keys=OFF')
        self.init_database()
        
        # 用于跟踪已处理的玩家
        self.processed_uids = set()
            
    def init_database(self):
        """初始化玩家资料相关的数据库表"""
        cursor = self.db_manager.get_connection().cursor()
        
        # 玩家基础资料表
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS player_profiles (
            uid TEXT PRIMARY KEY,
            current_name TEXT NOT NULL,
            avatar_url TEXT,
            join_date DATE,
            last_play_date DATE,
            total_play_time TEXT,
            gender TEXT,
            age INTEGER,
            location TEXT,
            bio TEXT,
            gold INTEGER,
            income INTEGER,
            charts_played_time TEXT,
            stable_charts INTEGER DEFAULT 0,
            unstable_charts INTEGER DEFAULT 0,
            chart_slots INTEGER DEFAULT 0,
            last_crawled TIMESTAMP NOT NULL,
            data_hash TEXT
        )
        ''')
        
        # 玩家头衔/称号表
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS player_titles (
            title_id INTEGER PRIMARY KEY AUTOINCREMENT,
            uid TEXT NOT NULL,
            title TEXT NOT NULL,
            acquired_date DATE,
            FOREIGN KEY (uid) REFERENCES player_profiles(uid),
            UNIQUE(uid, title)
        )
        ''')
        
        # 玩家成就徽章表 - 适配当前数据库结构（无achievement_img_url列）
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS player_achievements (
            uid TEXT NOT NULL,
            achievement_code INTEGER NOT NULL,
            acquired_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (uid, achievement_code),
            FOREIGN KEY (uid) REFERENCES player_profiles(uid)
        )
        ''')
        
        # 爬虫状态表（增强版）
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS player_profile_crawl_status (
            uid TEXT PRIMARY KEY,
            last_crawled TIMESTAMP,
            last_success TIMESTAMP,
            crawl_count INTEGER DEFAULT 0,
            success_count INTEGER DEFAULT 0,
            error_count INTEGER DEFAULT 0,
            last_error TEXT,
            data_hash TEXT,
            needs_update BOOLEAN DEFAULT 1,
            next_crawl_time TIMESTAMP,
            FOREIGN KEY (uid) REFERENCES player_profiles(uid)
        )
        ''')
        
        # 创建索引
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_player_titles_uid ON player_titles(uid)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_player_achievements_uid ON player_achievements(uid)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_crawl_status_last_crawled ON player_profile_crawl_status(last_crawled)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_crawl_status_needs_update ON player_profile_crawl_status(needs_update)')
        
        self.db_manager.get_connection().commit()
        self.logger.info("玩家资料数据库表初始化完成")
        
        # 确保player_identity表中有uid列
        self._ensure_uid_column()
    
    def _ensure_uid_column(self):
        """确保player_identity表有uid列"""
        try:
            cursor = self.db_manager.get_connection().cursor()
            cursor.execute("PRAGMA table_info(player_identity)")
            columns = [column[1] for column in cursor.fetchall()]
            
            if 'uid' not in columns:
                cursor.execute('ALTER TABLE player_identity ADD COLUMN uid TEXT')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_player_identity_uid ON player_identity(uid)')
                self.logger.info("已添加uid字段到player_identity表")
                
            self.db_manager.get_connection().commit()
        except Exception as e:
            self.logger.warning("检查player_identity表结构时出错: %s", e)
    
    def generate_data_hash(self, profile_data):
        """生成玩家资料数据的哈希值"""
        # 排除动态变化的字段
        data_to_hash = {
            k: v for k, v in profile_data.items() 
            if k not in ['last_crawled', 'data_hash']
        }
        data_str = json.dumps(data_to_hash, sort_keys=True, default=str)
        return hashlib.md5(data_str.encode('utf-8')).hexdigest()
    
    def extract_text_from_span(self, span_element):
        """从span元素中提取文本，处理&nbsp;等特殊字符"""
        if not span_element:
            return None
        
        text = span_element.get_text().strip()
        # 清理HTML实体和特殊字符
        text = text.replace('&nbsp;', ' ').strip()
        # 合并多个空格
        text = re.sub(r'\s+', ' ', text)
        return text if text else None
    
    def parse_player_profile_full(self, html, uid):
        """完整解析玩家个人主页 - 简化版本"""
        soup = BeautifulSoup(html, "html.parser")
        
        # 初始化profile数据
        profile = {
            "uid": uid,
            "current_name": None,
            "avatar_url": None,
            "join_date": None,
            "last_play_date": None,
            "total_play_time": None,
            "gender": None,
            "age": None,
            "location": None,
            "bio": None,
            "gold": None,
            "income": None,
            "charts_played_time": None,
            "stable_charts": 0,
            "unstable_charts": 0,
            "chart_slots": 0,  # 默认值为0
            "titles": [],
            "achievements": []
        }
        
        try:
            # 1. 提取用户名
            name_tag = soup.select_one("div.user_head .name span")
            if name_tag:
                profile["current_name"] = self.extract_text_from_span(name_tag)
                self.logger.debug("提取用户名: %s", profile["current_name"])
            else:
                # 备用方法：从meta标签提取
                og_title = soup.select_one("meta[property='og:title']")
                if og_title and og_title.get('content'):
                    profile["current_name"] = og_title.get('content').strip()
                    self.logger.debug("从meta标签提取用户名: %s", profile["current_name"])
            
            # 如果没有用户名，返回None
            if not profile["current_name"]:
                self.logger.warning("玩家 %s 没有用户名，可能页面无效", uid)
                return None
            
            # 2. 提取头像URL
            avatar_img = soup.select_one("div.user_head .coverb img")
            if avatar_img and 'src' in avatar_img.attrs:
                profile["avatar_url"] = avatar_img['src']
                self.logger.debug("提取头像URL: %s", profile["avatar_url"])
            
            # 3. 直接根据HTML结构提取信息
            user_head = soup.select_one("div.user_head .right")
            if user_head:
                # 获取所有段落
                paragraphs = user_head.find_all('p')
                
                for p in paragraphs:
                    # 每个段落可能有多个span，直接提取所有span
                    spans = p.find_all('span')
                    
                    for span in spans:
                        span_text = self.extract_text_from_span(span)
                        if not span_text:
                            continue
                        
                        # 根据内容判断是什么字段
                        if span_text.startswith('Joined since:'):
                            date_str = span_text.replace('Joined since:', '').strip()
                            try:
                                profile["join_date"] = datetime.strptime(date_str, "%Y-%m-%d").date()
                            except:
                                profile["join_date"] = date_str
                        elif span_text.startswith('Last play:'):
                            date_str = span_text.replace('Last play:', '').strip()
                            try:
                                profile["last_play_date"] = datetime.strptime(date_str, "%Y-%m-%d").date()
                            except:
                                profile["last_play_date"] = date_str
                        elif span_text.startswith('Played:'):
                            profile["total_play_time"] = span_text.replace('Played:', '').strip()
                        elif span_text.startswith('Gender:'):
                            profile["gender"] = span_text.replace('Gender:', '').strip()
                        elif span_text.startswith('Age:'):
                            age_text = span_text.replace('Age:', '').strip()
                            if age_text.isdigit():
                                profile["age"] = int(age_text)
                        elif span_text.startswith('Location:'):
                            profile["location"] = span_text.replace('Location:', '').strip()
                        elif span_text.startswith('Gold:'):
                            gold_text = span_text.replace('Gold:', '').replace(',', '').strip()
                            if gold_text.isdigit():
                                profile["gold"] = int(gold_text)
                        elif span_text.startswith('Income:'):
                            income_text = span_text.replace('Income:', '').replace(',', '').strip()
                            if income_text.isdigit():
                                profile["income"] = int(income_text)
                        elif span_text.startswith('Charts been played:'):
                            profile["charts_played_time"] = span_text.replace('Charts been played:', '').strip()
                        elif span_text.startswith('Stable charts:'):
                            stable_text = span_text.replace('Stable charts:', '').strip()
                            if stable_text.isdigit():
                                profile["stable_charts"] = int(stable_text)
                        elif span_text.startswith('Unstable charts:'):
                            unstable_text = span_text.replace('Unstable charts:', '').strip()
                            if unstable_text.isdigit():
                                profile["unstable_charts"] = int(unstable_text)
                        elif span_text.startswith('Chart slot:'):
                            slot_text = span_text.replace('Chart slot:', '').strip()
                            if slot_text.isdigit():
                                profile["chart_slots"] = int(slot_text)
            
            # 4. 提取头衔（使用em标签）
            title_ems = soup.select("div.user_head .name em")
            for em in title_ems:
                title = em.get_text().strip()
                if title and title not in profile["titles"]:
                    profile["titles"].append(title)
                    self.logger.debug("提取头衔: %s", title)
            
            # 5. 提取成就徽章 - 仅保存成就代码，不保存图片URL
            achievement_imgs = soup.select("div.ach img[src*='achieve']")
            for img in achievement_imgs:
                src = img.get('src', '')
                if not src:
                    continue
                
                # 过滤占位图
                if 'justfyHold' in img.get('class', []):
                    continue
                
                # 从URL中提取成就代码
                match = re.search(r'/achieve/(\d+)', src)
                if match:
                    achievement_code = int(match.group(1))
                    # 检查是否已存在
                    existing = [a for a in profile["achievements"] if a.get("code") == achievement_code]
                    if not existing:
                        profile["achievements"].append({
                            "code": achievement_code
                        })
                        self.logger.debug("提取成就: %d", achievement_code)
            
            # 6. 提取个人简介
            wiki_div = soup.select_one("div.wiki.g_rblock.curr")
            if wiki_div:
                bio_text = wiki_div.get_text().strip()
                if bio_text:
                    # 清理文本
                    bio_text = re.sub(r'\s+', ' ', bio_text)  # 合并空白字符
                    profile["bio"] = bio_text
                    self.logger.debug("提取个人简介，长度: %d", len(bio_text))
            
            self.logger.info("解析完成 - UID: %s, 用户名: %s, 头衔: %d个, 成就: %d个", 
                           uid, profile["current_name"], len(profile["titles"]), len(profile["achievements"]))
            
            return profile
            
        except Exception as e:
            self.logger.error("解析玩家 %s 个人主页失败: %s", uid, e, exc_info=True)
            
            # 即使部分失败，也返回已提取的数据
            if profile["current_name"]:
                return profile
            return None
    
    def fetch_player_profile(self, uid):
        """获取玩家个人主页HTML - 简化版本"""
        url = PLAYER_PROFILE_URL.format(uid=uid)
        
        try:
            self.logger.debug("请求玩家主页: %s", url)
            response = self.session.get(url, timeout=30)
            
            # 检查状态码
            if response.status_code == 404:
                self.logger.info("玩家 %s 不存在 (404)", uid)
                return None
            elif response.status_code != 200:
                self.logger.warning("玩家 %s 返回状态码: %d", uid, response.status_code)
                return None
            
            # 检查页面内容是否有效
            if len(response.content) < 100:
                self.logger.warning("玩家 %s 页面内容过短，可能无效", uid)
                return None
            
            # 直接返回HTML，让解析函数处理
            return response.text
            
        except requests.exceptions.RequestException as e:
            self.logger.error("请求失败获取玩家 %s: %s", uid, e)
            return None
        except Exception as e:
            self.logger.error("获取玩家 %s 数据时出错: %s", uid, e)
            return None
    
    def save_player_profile(self, profile_data):
        """保存玩家资料到数据库"""
        if not profile_data:
            return False
        
        cursor = self.db_manager.get_connection().cursor()
        crawl_time = datetime.now()
        
        try:
            uid = profile_data["uid"]
            
            # 生成数据哈希
            data_hash = self.generate_data_hash(profile_data)
            
            # 检查是否需要更新（数据是否有变化）
            cursor.execute(
                "SELECT data_hash FROM player_profiles WHERE uid = ?",
                (uid,)
            )
            result = cursor.fetchone()
            
            if result and result[0] == data_hash:
                self.logger.debug("玩家 %s 数据未变化，跳过保存", uid)
                # 只更新最后爬取时间
                cursor.execute(
                    "UPDATE player_profiles SET last_crawled = ? WHERE uid = ?",
                    (crawl_time, uid)
                )
                
                # 更新爬虫状态
                cursor.execute('''
                INSERT OR REPLACE INTO player_profile_crawl_status 
                (uid, last_crawled, last_success, crawl_count, success_count, error_count, 
                 last_error, data_hash, needs_update, next_crawl_time)
                VALUES (?, ?, ?, 
                       COALESCE((SELECT crawl_count FROM player_profile_crawl_status WHERE uid = ?), 0) + 1, 
                       COALESCE((SELECT success_count FROM player_profile_crawl_status WHERE uid = ?), 0) + 1,
                       COALESCE((SELECT error_count FROM player_profile_crawl_status WHERE uid = ?), 0),
                       NULL, ?, 0, ?)
                ''', (
                    uid, crawl_time, crawl_time, uid, uid, uid, 
                    data_hash, crawl_time + timedelta(days=30)
                ))
                
                self.db_manager.get_connection().commit()
                self.logger.info("玩家 %s 数据未变化，仅更新时间", uid)
                return True
            
            # 准备数据，确保数据类型正确
            stable_charts = profile_data.get("stable_charts", 0)
            if not isinstance(stable_charts, int):
                try:
                    stable_charts = int(stable_charts)
                except:
                    stable_charts = 0
            
            unstable_charts = profile_data.get("unstable_charts", 0)
            if not isinstance(unstable_charts, int):
                try:
                    unstable_charts = int(unstable_charts)
                except:
                    unstable_charts = 0
            
            chart_slots = profile_data.get("chart_slots", 0)
            if not isinstance(chart_slots, int):
                try:
                    chart_slots = int(chart_slots)
                except:
                    chart_slots = 0
            
            # 保存到player_profiles表
            cursor.execute('''
            INSERT OR REPLACE INTO player_profiles 
            (uid, current_name, avatar_url, join_date, last_play_date, total_play_time,
             gender, age, location, bio, gold, income, charts_played_time,
             stable_charts, unstable_charts, chart_slots, last_crawled, data_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                profile_data["uid"], 
                profile_data.get("current_name", ""),
                profile_data.get("avatar_url"),
                profile_data.get("join_date"),
                profile_data.get("last_play_date"),
                profile_data.get("total_play_time"),
                profile_data.get("gender"),
                profile_data.get("age"),
                profile_data.get("location"),
                profile_data.get("bio"),
                profile_data.get("gold"),
                profile_data.get("income"),
                profile_data.get("charts_played_time"),
                stable_charts,
                unstable_charts,
                chart_slots,
                crawl_time, 
                data_hash
            ))
            
            # 删除旧的头衔记录，然后重新插入
            cursor.execute("DELETE FROM player_titles WHERE uid = ?", (uid,))
            
            # 保存头衔
            if profile_data.get("titles"):
                for title in profile_data["titles"]:
                    if title:
                        cursor.execute('''
                        INSERT INTO player_titles (uid, title) VALUES (?, ?)
                        ''', (uid, title))
            
            # 删除旧的成就记录，然后重新插入
            cursor.execute("DELETE FROM player_achievements WHERE uid = ?", (uid,))
            
            # 保存成就 - 适配当前表结构（无achievement_img_url列）
            if profile_data.get("achievements"):
                for achievement in profile_data["achievements"]:
                    if achievement.get("code"):
                        cursor.execute('''
                        INSERT INTO player_achievements (uid, achievement_code)
                        VALUES (?, ?)
                        ''', (uid, achievement["code"]))
            
            # 更新爬虫状态
            cursor.execute('''
            INSERT OR REPLACE INTO player_profile_crawl_status 
            (uid, last_crawled, last_success, crawl_count, success_count, error_count, 
             last_error, data_hash, needs_update, next_crawl_time)
            VALUES (?, ?, ?, 
                   COALESCE((SELECT crawl_count FROM player_profile_crawl_status WHERE uid = ?), 0) + 1, 
                   COALESCE((SELECT success_count FROM player_profile_crawl_status WHERE uid = ?), 0) + 1,
                   COALESCE((SELECT error_count FROM player_profile_crawl_status WHERE uid = ?), 0),
                   NULL, ?, 0, ?)
            ''', (
                uid, crawl_time, crawl_time, uid, uid, uid, 
                data_hash, crawl_time + timedelta(days=30)
            ))
            
            self.db_manager.get_connection().commit()
            self.logger.info("✓ 玩家 %s 资料保存成功", uid)
            return True
            
        except Exception as e:
            self.logger.error("保存玩家 %s 资料失败: %s", profile_data.get("uid", "未知"), e, exc_info=True)
            
            # 记录错误状态
            try:
                cursor.execute('''
                INSERT OR REPLACE INTO player_profile_crawl_status 
                (uid, last_crawled, last_success, crawl_count, success_count, error_count, 
                 last_error, data_hash, needs_update, next_crawl_time)
                VALUES (?, ?, 
                       (SELECT last_success FROM player_profile_crawl_status WHERE uid = ?),
                       COALESCE((SELECT crawl_count FROM player_profile_crawl_status WHERE uid = ?), 0) + 1, 
                       COALESCE((SELECT success_count FROM player_profile_crawl_status WHERE uid = ?), 0),
                       COALESCE((SELECT error_count FROM player_profile_crawl_status WHERE uid = ?), 0) + 1,
                       ?, NULL, 1, ?)
                ''', (
                    uid, crawl_time, uid, uid, uid, uid, str(e),
                    crawl_time + timedelta(hours=6)
                ))
                self.db_manager.get_connection().commit()
            except Exception as e2:
                self.logger.error("更新爬虫状态失败: %s", e2)
            
            self.db_manager.get_connection().rollback()
            return False
    
    def crawl_player_profile(self, uid, print_only=False):
        """爬取单个玩家的个人主页"""
        self.logger.info("开始爬取玩家: %s", uid)
        
        # 检查是否已处理过
        if not print_only and uid in self.processed_uids:
            self.logger.debug("玩家 %s 已处理过，跳过", uid)
            return True
        
        try:
            # 获取HTML页面
            html = self.fetch_player_profile(uid)
            if not html:
                self.logger.info("玩家 %s 页面获取失败或无数据，跳过", uid)
                return False
            
            # 解析HTML
            profile_data = self.parse_player_profile_full(html, uid)
            if not profile_data:
                self.logger.info("玩家 %s 数据解析失败，跳过", uid)
                return False
            
            # 如果是仅打印模式
            if print_only:
                return self.print_profile_data(profile_data)
            
            # 保存到数据库
            success = self.save_player_profile(profile_data)
            if success:
                self.processed_uids.add(uid)
                return True
            else:
                return False
                
        except Exception as e:
            self.logger.error("爬取玩家 %s 时出错: %s", uid, e, exc_info=True)
            return False
    
    def print_profile_data(self, profile_data):
        """在终端打印解析出的玩家数据"""
        print("\n" + "="*80)
        print("玩家资料解析结果 (仅打印，不保存)")
        print("="*80)
        
        # 基本信息
        print(f"UID: {profile_data.get('uid', 'N/A')}")
        print(f"用户名: {profile_data.get('current_name', 'N/A')}")
        print(f"头像URL: {profile_data.get('avatar_url', 'N/A')[:50]}..." if profile_data.get('avatar_url') else "头像URL: N/A")
        
        # 日期信息
        print(f"\n时间信息:")
        print(f"  加入日期: {profile_data.get('join_date', 'N/A')}")
        print(f"  最后游玩: {profile_data.get('last_play_date', 'N/A')}")
        print(f"  总游玩时长: {profile_data.get('total_play_time', 'N/A')}")
        
        # 个人信息
        print(f"\n个人信息:")
        print(f"  性别: {profile_data.get('gender', 'N/A')}")
        print(f"  年龄: {profile_data.get('age', 'N/A')}")
        print(f"  地区: {profile_data.get('location', 'N/A')}")
        
        # 游戏数据
        print(f"\n游戏数据:")
        print(f"  金币: {profile_data.get('gold', 'N/A')}")
        print(f"  收入: {profile_data.get('income', 'N/A')}")
        print(f"  谱面游玩时长: {profile_data.get('charts_played_time', 'N/A')}")
        print(f"  稳定谱面: {profile_data.get('stable_charts', 'N/A')}")
        print(f"  不稳定谱面: {profile_data.get('unstable_charts', 'N/A')}")
        print(f"  谱面槽位: {profile_data.get('chart_slots', 'N/A')}")
        
        # 头衔
        titles = profile_data.get('titles', [])
        if titles:
            print(f"\n头衔 ({len(titles)} 个):")
            for i, title in enumerate(titles, 1):
                print(f"  {i}. {title}")
        else:
            print(f"\n头衔: 无")
        
        # 成就 - 只显示成就代码，无图片URL
        achievements = profile_data.get('achievements', [])
        if achievements:
            print(f"\n成就徽章 ({len(achievements)} 个):")
            for i, achievement in enumerate(achievements, 1):
                print(f"  {i}. 成就代码: {achievement.get('code', 'N/A')}")
        else:
            print(f"\n成就徽章: 无")
        
        # 个人简介
        bio = profile_data.get('bio', '')
        if bio:
            print(f"\n个人简介 (长度: {len(bio)}):")
            # 限制显示长度
            if len(bio) > 500:
                print(f"  {bio[:500]}...")
            else:
                print(f"  {bio}")
        else:
            print(f"\n个人简介: 无")
        
        # 数据哈希
        data_hash = self.generate_data_hash(profile_data)
        print(f"\n数据哈希: {data_hash[:16]}...")
        
        print("\n" + "="*80)
        
        return True
    
    def test_parse_and_print(self, uid):
        """测试解析并打印单个玩家的数据"""
        self.logger.info("测试解析玩家: %s", uid)
        
        # 获取HTML页面
        html = self.fetch_player_profile(uid)
        if not html:
            self.logger.error("获取玩家 %s 页面失败或无数据", uid)
            return False
        
        # 解析HTML
        profile_data = self.parse_player_profile_full(html, uid)
        if not profile_data:
            self.logger.error("解析玩家 %s 数据失败", uid)
            return False
        
        # 打印数据
        self.print_profile_data(profile_data)
        return True
    
    def crawl_players_batch(self, uid_list, max_workers=3, requests_per_minute=15, print_only=False):
        """批量爬取玩家资料"""
        self.logger.info("开始批量爬取，共 %d 个玩家，模式: %s", 
                       len(uid_list), "仅打印" if print_only else "保存到数据库")
        
        success_count = 0
        fail_count = 0
        
        # 使用线程池并发爬取
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_uid = {
                executor.submit(self.crawl_player_profile, uid, print_only): uid 
                for uid in uid_list
            }
            
            for future in as_completed(future_to_uid):
                uid = future_to_uid[future]
                
                try:
                    result = future.result()
                    if result:
                        success_count += 1
                        if not print_only:
                            self.logger.info("✓ 玩家 %s 爬取成功 (进度: %d/%d)", 
                                           uid, success_count, len(uid_list))
                    else:
                        fail_count += 1
                        if not print_only:
                            self.logger.info("✗ 玩家 %s 爬取失败或无数据 (进度: %d/%d)", 
                                           uid, success_count + fail_count, len(uid_list))
                except Exception as e:
                    fail_count += 1
                    if not print_only:
                        self.logger.error("处理玩家 %s 时出错: %s", uid, e)
                
                # 更新进度
                with progress_lock:
                    crawl_progress['current'] = success_count + fail_count
                    crawl_progress['success'] = success_count
                    crawl_progress['fail'] = fail_count
                    crawl_progress['total'] = len(uid_list)
        
        if not print_only:
            self.logger.info("批量爬取完成: 成功 %d, 失败 %d", success_count, fail_count)
        return success_count, fail_count
    
    def crawl_from_database(self, limit=None, days_since_last_crawl=30):
        """从数据库中获取需要更新的玩家UID"""
        cursor = self.db_manager.get_connection().cursor()
        
        try:
            # 获取需要更新的玩家
            cutoff_date = datetime.now() - timedelta(days=days_since_last_crawl)
            
            query = '''
            SELECT uid FROM player_profile_crawl_status 
            WHERE (needs_update = 1 OR last_crawled IS NULL OR last_crawled < ?)
            ORDER BY last_crawled ASC NULLS FIRST
            '''
            
            params = [cutoff_date]
            
            if limit:
                query += " LIMIT ?"
                params.append(limit)
            
            cursor.execute(query, params)
            results = cursor.fetchall()
            
            uid_list = [row[0] for row in results]
            self.logger.info("从数据库找到 %d 个需要更新的玩家", len(uid_list))
            return uid_list
            
        except Exception as e:
            self.logger.error("从数据库获取待爬取玩家失败: %s", e)
            return []
    
    def crawl_from_leaderboard(self, mode=0, limit=100):
        """从排行榜获取玩家UID"""
        from malody_rankings import crawl_mode_player, parse_player_list
        
        try:
            self.logger.info("从排行榜模式 %d 获取玩家", mode)
            
            # 直接使用排行榜的session
            url = f"https://m.mugzone.net/page/all/player?from=0&mode={mode}"
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            
            # 使用现有的解析函数
            players = parse_player_list(response.text)
            
            # 提取有效的UID
            uid_list = []
            for player in players:
                if player.get('player_id'):
                    uid_list.append(player['player_id'])
            
            # 去重和限制数量
            uid_list = list(set(uid_list))
            if limit and len(uid_list) > limit:
                uid_list = uid_list[:limit]
            
            self.logger.info("从排行榜获取到 %d 个玩家UID", len(uid_list))
            return uid_list
            
        except Exception as e:
            self.logger.error("从排行榜获取玩家失败: %s", e)
            return []
    
    def crawl_by_uid_range(self, start_uid, end_uid, step=1, print_only=False):
        """按UID范围爬取"""
        uid_list = list(range(start_uid, end_uid + 1, step))
        self.logger.info("按UID范围爬取: %d-%d (共 %d 个)", start_uid, end_uid, len(uid_list))
        return self.crawl_players_batch(uid_list, print_only=print_only)
    
    def get_progress_status(self):
        """获取当前爬取状态"""
        with progress_lock:
            if not crawl_progress:
                return "无进度信息"
            
            return (
                f"当前进度: {crawl_progress.get('current', 0)}/{crawl_progress.get('total', 0)}\n"
                f"成功: {crawl_progress.get('success', 0)}\n"
                f"失败: {crawl_progress.get('fail', 0)}"
            )
    
    def test_connection(self):
        """测试连接"""
        test_uid = "858752"  # 使用之前成功的UID作为测试
        self.logger.info("测试连接，爬取玩家: %s", test_uid)
        
        success = self.crawl_player_profile(test_uid)
        if success:
            self.logger.info("连接测试成功")
            return True
        else:
            self.logger.error("连接测试失败")
            return False

def signal_handler(sig, frame):
    """处理终止信号"""
    global stop_requested
    with stop_lock:
        stop_requested = True
    logging.getLogger().info("收到终止信号，正在安全退出...")
    time.sleep(1)
    sys.exit(0)

def read_uid_file(file_path):
    """读取UID文件，忽略空行和注释行（# 或 //）"""
    uid_list = []
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                # 忽略空行和注释行
                if not line or line.startswith('#') or line.startswith('//'):
                    continue
                uid_list.append(line)
        return uid_list
    except Exception as e:
        logging.getLogger().error("读取UID文件失败: %s", e)
        return None

def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='玩家个人主页资料爬虫')
    
    # 爬取源选项
    source_group = parser.add_mutually_exclusive_group()
    source_group.add_argument('--uid', type=str, help='单个玩家UID')
    source_group.add_argument('--uid-list', type=str, help='逗号分隔的UID列表')
    source_group.add_argument('--uid-range', type=str, help='UID范围，格式: start-end (如: 1000-2000)')
    source_group.add_argument('--uid-file', type=str, help='包含UID列表的文件，每行一个')
    source_group.add_argument('--from-db', action='store_true', help='从数据库获取需要更新的玩家')
    source_group.add_argument('--from-leaderboard', action='store_true', help='从排行榜获取玩家')
    source_group.add_argument('--leaderboard-mode', type=int, default=0, help='排行榜模式 (默认: 0)')
    
    # 控制选项
    parser.add_argument('--limit', type=int, help='最大爬取数量')
    parser.add_argument('--days-since-update', type=int, default=30, 
                       help='多少天未更新视为需要更新 (默认: 30天)')
    parser.add_argument('--max-workers', type=int, default=3, 
                       help='最大并发线程数 (默认: 3)')
    parser.add_argument('--rpm', type=int, default=15, 
                       help='每分钟请求数 (默认: 15)')
    parser.add_argument('--test', action='store_true', help='测试连接')
    parser.add_argument('--print-only', action='store_true', 
                       help='仅解析并打印数据，不保存到数据库')
    parser.add_argument('--status', action='store_true', help='显示数据库状态')
    parser.add_argument('--log-level', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'], 
                       default='INFO', help='日志级别 (默认: INFO)')
    parser.add_argument('--log-file', help='指定日志文件路径')
    # 新增参数：禁用默认读取players.txt
    parser.add_argument('--no-default-players', action='store_true',
                       help='不自动使用默认的players.txt文件作为UID源')
    
    args = parser.parse_args()
    
    # 设置信号处理器
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # 设置日志
    log_level = getattr(logging, args.log_level)
    setup_detailed_logging(log_level=log_level, log_file=args.log_file)
    
    logger = logging.getLogger(__name__)
    logger.info("玩家个人主页爬虫启动，参数: %s", vars(args))
    
    # 初始化数据库（如果需要保存的话）
    if not args.print_only:
        init_database()
    
    # 创建爬虫实例
    crawler = PlayerProfileCrawler()
    
    # 显示状态
    if args.status:
        if not args.print_only:
            cursor = crawler.db_manager.get_connection().cursor()
            cursor.execute("SELECT COUNT(*) FROM player_profiles")
            profile_count = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM player_titles")
            title_count = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM player_achievements")
            achievement_count = cursor.fetchone()[0]
            
            cursor.execute('''
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN needs_update = 1 THEN 1 ELSE 0 END) as need_update,
                SUM(CASE WHEN last_crawled IS NULL THEN 1 ELSE 0 END) as never_crawled
            FROM player_profile_crawl_status
            ''')
            status_result = cursor.fetchone()
            
            print("玩家资料数据库状态:")
            print(f"  玩家资料数: {profile_count}")
            print(f"  头衔记录数: {title_count}")
            print(f"  成就记录数: {achievement_count}")
            print(f"  爬虫状态记录: {status_result[0]}")
            print(f"  需要更新: {status_result[1]}")
            print(f"  从未爬取: {status_result[2]}")
        else:
            print("在 --print-only 模式下无法显示数据库状态")
        return
    
    # 测试连接
    if args.test:
        if crawler.test_connection():
            logger.info("连接测试成功")
        else:
            logger.error("连接测试失败")
        return
    
    # 准备UID列表
    uid_list = []
    
    # 检查是否指定了任何UID源
    has_source = any([
        args.uid, args.uid_list, args.uid_range, 
        args.uid_file, args.from_db, args.from_leaderboard
    ])
    
    # 如果没有指定任何源且没有禁用默认players.txt，则自动使用默认文件
    if not has_source and not args.no_default_players:
        default_file = "players.txt"
        if os.path.exists(default_file):
            logger.info("未指定UID源，自动使用默认文件: %s", default_file)
            args.uid_file = default_file
        else:
            logger.error("未指定任何UID源，且默认文件 %s 不存在，请指定源或创建文件", default_file)
            return
    
    # 按优先级处理各源
    if args.uid:
        uid_list = [args.uid.strip()]
    
    elif args.uid_list:
        uid_list = [uid.strip() for uid in args.uid_list.split(',') if uid.strip()]
    
    elif args.uid_range:
        try:
            start_str, end_str = args.uid_range.split('-')
            start_uid = int(start_str.strip())
            end_uid = int(end_str.strip())
            uid_list = list(range(start_uid, end_uid + 1))
        except ValueError:
            logger.error("UID范围格式错误，应为: start-end (如: 1000-2000)")
            return
    
    elif args.uid_file:
        # 使用增强的文件读取函数，支持注释和空行过滤
        uid_list = read_uid_file(args.uid_file)
        if uid_list is None:
            return
    
    elif args.from_db and not args.print_only:
        # 仅当需要保存时才从数据库获取
        uid_list = crawler.crawl_from_database(
            limit=args.limit, 
            days_since_last_crawl=args.days_since_update
        )
    
    elif args.from_leaderboard:
        uid_list = crawler.crawl_from_leaderboard(
            mode=args.leaderboard_mode,
            limit=args.limit
        )
    
    # 如果没有获取到任何UID，给出提示
    if not uid_list:
        logger.warning("没有找到需要爬取的玩家")
        return
    
    # 限制爬取数量
    if args.limit and len(uid_list) > args.limit:
        uid_list = uid_list[:args.limit]
    
    logger.info("开始爬取 %d 个玩家资料，模式: %s", 
               len(uid_list), "仅打印" if args.print_only else "保存到数据库")
    
    # 初始化进度
    with progress_lock:
        crawl_progress['current'] = 0
        crawl_progress['success'] = 0
        crawl_progress['fail'] = 0
        crawl_progress['total'] = len(uid_list)
    
    # 批量爬取
    success, fail = crawler.crawl_players_batch(
        uid_list, 
        max_workers=args.max_workers,
        requests_per_minute=args.rpm,
        print_only=args.print_only
    )
    
    if not args.print_only:
        logger.info("爬取完成: 成功 %d, 失败 %d", success, fail)
        
        # 显示最终状态
        cursor = crawler.db_manager.get_connection().cursor()
        cursor.execute("SELECT COUNT(*) FROM player_profiles")
        total = cursor.fetchone()[0]
        logger.info("数据库中共有 %d 个玩家资料", total)

if __name__ == "__main__":
    main()
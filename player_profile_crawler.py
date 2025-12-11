#!/usr/bin/env python3
"""
玩家个人主页资料爬虫 - 优化版
用于爬取玩家的详细个人信息、头衔、成就等
采用真正的归一化存储，大幅减少数据冗余
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
    logger.info("玩家个人主页爬虫启动 (优化版)")
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
                "User-Agent": "Mozilla/5.0 (Android 12; Mobile) Python Script",
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
        self.init_database()
        
        # 用于跟踪已处理的玩家
        self.processed_uids = set()
        
    def init_database(self):
        """初始化玩家资料相关的数据库表 - 优化版"""
        cursor = self.db_manager.get_connection().cursor()
        
        # 玩家基础资料表（简化版）
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
            last_crawled TIMESTAMP DEFAULT NULL,
            data_hash TEXT
        )
        ''')
        
        # 成就目录表（存储所有可能的成就）
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS achievement_catalog (
            code INTEGER PRIMARY KEY,
            name TEXT,
            description TEXT,
            created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        
        # 玩家成就关联表（真正的优化版）
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS player_achievements (
            uid TEXT NOT NULL,
            achievement_code INTEGER NOT NULL,
            acquired_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (uid, achievement_code),
            FOREIGN KEY (uid) REFERENCES player_profiles(uid),
            FOREIGN KEY (achievement_code) REFERENCES achievement_catalog(code)
        )
        ''')
        
        # 玩家头衔表（简化的）
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS player_titles (
            uid TEXT NOT NULL,
            title TEXT NOT NULL,
            PRIMARY KEY (uid, title),
            FOREIGN KEY (uid) REFERENCES player_profiles(uid)
        )
        ''')
        
        # 创建索引
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_player_profiles_last_crawled ON player_profiles(last_crawled)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_player_achievements_uid ON player_achievements(uid)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_player_titles_uid ON player_titles(uid)')
        
        self.db_manager.get_connection().commit()
        self.logger.info("玩家资料数据库表初始化完成（优化版）")
        
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
            "chart_slots": 0,
            "titles": [],
            "achievements": []  # 只存储成就代码
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
            
            # 5. 提取成就徽章（只提取代码）
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
                    
                    # 只存储成就代码
                    if achievement_code not in profile["achievements"]:
                        profile["achievements"].append(achievement_code)
                        self.logger.debug("提取成就代码: %d", achievement_code)
            
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
    
    def needs_crawl(self, uid, days_interval=30):
        """判断玩家是否需要重新爬取"""
        cursor = self.db_manager.get_connection().cursor()
        
        cursor.execute(
            "SELECT last_crawled FROM player_profiles WHERE uid = ?",
            (uid,)
        )
        result = cursor.fetchone()
        
        if not result or not result[0]:
            return True  # 从未爬取过
        
        last_crawled = datetime.fromisoformat(result[0]) if isinstance(result[0], str) else result[0]
        days_passed = (datetime.now() - last_crawled).days
        
        return days_passed >= days_interval
    
    def _save_achievements_simple(self, uid, achievement_codes):
        """简化保存成就数据"""
        if not achievement_codes:
            return
        
        cursor = self.db_manager.get_connection().cursor()
        
        try:
            # 1. 确保成就在目录中存在（只插入新的）
            for code in achievement_codes:
                # 检查是否已存在
                cursor.execute("SELECT 1 FROM achievement_catalog WHERE code = ?", (code,))
                if not cursor.fetchone():
                    # 只插入代码，其他信息可以通过爬虫补充
                    cursor.execute(
                        "INSERT INTO achievement_catalog (code) VALUES (?)",
                        (code,)
                    )
            
            # 2. 删除旧的关联
            cursor.execute("DELETE FROM player_achievements WHERE uid = ?", (uid,))
            
            # 3. 插入新的关联
            for code in achievement_codes:
                cursor.execute(
                    "INSERT OR IGNORE INTO player_achievements (uid, achievement_code) VALUES (?, ?)",
                    (uid, code)
                )
            
            self.logger.debug("保存成就: UID=%s, 成就数=%d", uid, len(achievement_codes))
            
        except Exception as e:
            self.logger.error("保存成就数据失败: %s", e)
            raise
    
    def save_player_profile(self, profile_data):
        """保存玩家资料到数据库 - 优化版"""
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
                # 数据未变化，只更新最后爬取时间
                cursor.execute(
                    "UPDATE player_profiles SET last_crawled = ? WHERE uid = ?",
                    (crawl_time, uid)
                )
                self.db_manager.get_connection().commit()
                self.logger.debug("玩家 %s 数据未变化，仅更新时间", uid)
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
                        cursor.execute(
                            "INSERT INTO player_titles (uid, title) VALUES (?, ?)",
                            (uid, title)
                        )
            
            # 保存成就（使用新方法）
            self._save_achievements_simple(uid, profile_data.get("achievements", []))
            
            self.db_manager.get_connection().commit()
            self.logger.info("✓ 玩家 %s 资料保存成功", uid)
            return True
            
        except Exception as e:
            self.logger.error("保存玩家 %s 资料失败: %s", profile_data.get("uid", "未知"), e, exc_info=True)
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
        
        # 成就
        achievements = profile_data.get('achievements', [])
        if achievements:
            print(f"\n成就代码 ({len(achievements)} 个):")
            for i, code in enumerate(achievements, 1):
                print(f"  {i}. 代码: {code}")
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
            SELECT uid FROM player_profiles 
            WHERE last_crawled IS NULL OR last_crawled < ?
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
    
    def crawl_from_other_tables(self, limit=None, days_since_last_crawl=30, 
                               exclude_existing=True, priority_order=True):
        """
        从数据库其他表中提取出现的UID并进行爬取
        
        Args:
            limit: 最大爬取数量
            days_since_last_crawl: 多少天未更新视为需要更新
            exclude_existing: 是否排除已经在player_profiles表中的UID
            priority_order: 是否按优先级排序（最后出现时间倒序）
        """
        cursor = self.db_manager.get_connection().cursor()
        
        try:
            # 从其他表中提取UID
            self.logger.info("从数据库其他表中提取UID...")
            
            # 从不同的表中提取UID
            queries = [
                ("player_identity", "SELECT DISTINCT uid FROM player_identity WHERE uid IS NOT NULL AND uid != ''"),
                ("player_aliases", "SELECT DISTINCT uid FROM player_aliases WHERE uid IS NOT NULL AND uid != ''"),
                ("player_rankings", "SELECT DISTINCT uid FROM player_rankings WHERE uid IS NOT NULL AND uid != ''"),
                ("charts", "SELECT DISTINCT creator_uid FROM charts WHERE creator_uid IS NOT NULL AND creator_uid != ''"),
                ("charts", "SELECT DISTINCT stabled_by_uid FROM charts WHERE stabled_by_uid IS NOT NULL AND stabled_by_uid != ''")
            ]
            
            all_uids = set()
            
            for table_name, query in queries:
                try:
                    cursor.execute(query)
                    results = cursor.fetchall()
                    count = len(results)
                    
                    for row in results:
                        if row[0]:  # 确保UID不为空
                            all_uids.add(str(row[0]).strip())
                    
                    self.logger.info("从 %s 表中提取到 %d 个UID", table_name, count)
                except Exception as e:
                    self.logger.warning("从表 %s 提取UID失败: %s", table_name, e)
            
            self.logger.info("总共从数据库提取到 %d 个唯一UID", len(all_uids))
            
            if not all_uids:
                self.logger.warning("没有从数据库其他表中提取到UID")
                return []
            
            # 如果需要排除已经存在的UID
            if exclude_existing:
                try:
                    # 查询已经在player_profiles表中的UID
                    cursor.execute("SELECT uid FROM player_profiles")
                    existing_uids = {str(row[0]).strip() for row in cursor.fetchall()}
                    
                    # 排除已经存在的UID
                    all_uids = all_uids - existing_uids
                    self.logger.info("排除已在player_profiles表中的UID，剩余 %d 个", len(all_uids))
                except Exception as e:
                    self.logger.warning("查询已有UID失败: %s，跳过排除", e)
            
            # 获取需要更新的UID（根据最后爬取时间）
            if days_since_last_crawl > 0:
                try:
                    cutoff_date = datetime.now() - timedelta(days=days_since_last_crawl)
                    
                    # 查询最近爬取过的UID
                    cursor.execute(
                        "SELECT uid FROM player_profiles WHERE last_crawled >= ?",
                        (cutoff_date,)
                    )
                    
                    recently_crawled = {str(row[0]).strip() for row in cursor.fetchall()}
                    
                    # 排除最近已经爬取过的UID
                    all_uids = all_uids - recently_crawled
                    self.logger.info("排除最近 %d 天内已爬取的UID，剩余 %d 个", 
                                   days_since_last_crawl, len(all_uids))
                except Exception as e:
                    self.logger.warning("查询最近爬取UID失败: %s，跳过过滤", e)
            
            if not all_uids:
                self.logger.info("没有需要爬取的新UID")
                return []
            
            # 转换为列表
            uid_list = list(all_uids)
            
            # 如果需要按优先级排序（最后出现时间倒序）
            if priority_order and len(uid_list) > 0:
                try:
                    # 构建一个查询来获取每个UID最后出现的时间
                    # 这里我们简化处理：从player_rankings表中获取最后出现时间
                    uid_placeholders = ','.join(['?'] * len(uid_list))
                    
                    cursor.execute(f'''
                    SELECT uid, MAX(crawl_time) as last_seen
                    FROM player_rankings 
                    WHERE uid IN ({uid_placeholders})
                    GROUP BY uid
                    ORDER BY last_seen DESC
                    ''', uid_list)
                    
                    ordered_results = cursor.fetchall()
                    
                    if ordered_results:
                        # 按照查询结果的顺序重新排序UID列表
                        ordered_uids = [str(row[0]) for row in ordered_results]
                        
                        # 添加那些没有在player_rankings表中出现的UID
                        missing_uids = set(uid_list) - set(ordered_uids)
                        uid_list = ordered_uids + list(missing_uids)
                        
                        self.logger.info("按最后出现时间排序完成")
                except Exception as e:
                    self.logger.warning("按优先级排序失败: %s，使用原始顺序", e)
            
            # 限制数量
            if limit and len(uid_list) > limit:
                self.logger.info("限制爬取数量为 %d 个", limit)
                uid_list = uid_list[:limit]
            
            self.logger.info("最终确定 %d 个UID需要爬取", len(uid_list))
            return uid_list
            
        except Exception as e:
            self.logger.error("从其他表提取UID失败: %s", e, exc_info=True)
            return []
    
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
    
    # ========== 新增功能：数据清理和优化 ==========
    
    def cleanup_old_data(self):
        """清理旧的数据结构 - 修复版"""
        cursor = self.db_manager.get_connection().cursor()
        
        try:
            # 检查是否需要清理
            self.logger.info("检查旧数据表...")
            
            # 1. 检查并删除旧的爬虫状态表
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='player_profile_crawl_status'")
            if cursor.fetchone():
                self.logger.info("删除旧表: player_profile_crawl_status")
                cursor.execute("DROP TABLE IF EXISTS player_profile_crawl_status")
            
            # 2. 检查并删除旧的优化成就表
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='player_achievements_optimized'")
            if cursor.fetchone():
                self.logger.info("删除旧表: player_achievements_optimized")
                cursor.execute("DROP TABLE IF EXISTS player_achievements_optimized")
            
            # 3. 简化player_achievements表结构（如果存在URL列）
            try:
                cursor.execute("PRAGMA table_info(player_achievements)")
                columns = [column[1] for column in cursor.fetchall()]
                
                if 'achievement_img_url' in columns:
                    self.logger.info("简化player_achievements表结构...")
                    
                    # 创建临时表
                    cursor.execute('''
                    CREATE TABLE temp_player_achievements AS 
                    SELECT uid, achievement_code FROM player_achievements 
                    WHERE achievement_code IS NOT NULL
                    ''')
                    
                    # 删除原表
                    cursor.execute("DROP TABLE player_achievements")
                    
                    # 创建新表
                    cursor.execute('''
                    CREATE TABLE player_achievements (
                        uid TEXT NOT NULL,
                        achievement_code INTEGER NOT NULL,
                        acquired_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (uid, achievement_code),
                        FOREIGN KEY (uid) REFERENCES player_profiles(uid),
                        FOREIGN KEY (achievement_code) REFERENCES achievement_catalog(code)
                    )
                    ''')
                    
                    # 复制数据
                    cursor.execute('''
                    INSERT OR IGNORE INTO player_achievements (uid, achievement_code)
                    SELECT uid, achievement_code FROM temp_player_achievements
                    ''')
                    
                    # 删除临时表
                    cursor.execute("DROP TABLE temp_player_achievements")
                    
                    self.logger.info("player_achievements表结构简化完成")
            except Exception as e:
                self.logger.warning(f"简化成就表结构时出错: {e}")
            
            self.db_manager.get_connection().commit()
            self.logger.info("数据清理完成")
            return True
            
        except Exception as e:
            self.logger.error(f"清理数据失败: {e}", exc_info=True)
            self.db_manager.get_connection().rollback()
            return False
    
    def migrate_achievements_data(self):
        """迁移旧的成就数据到新的优化表"""
        self.logger.info("开始迁移成就数据到优化表...")
        
        cursor = self.db_manager.get_connection().cursor()
        
        try:
            # 1. 创建成就目录表（如果不存在）
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS achievement_catalog (
                code INTEGER PRIMARY KEY,
                name TEXT,
                description TEXT,
                created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            ''')
            
            # 2. 从旧表中提取不重复的成就代码
            cursor.execute('''
            SELECT DISTINCT achievement_code 
            FROM player_achievements 
            WHERE achievement_code IS NOT NULL
            ''')
            
            achievement_codes = [row[0] for row in cursor.fetchall()]
            self.logger.info(f"发现 {len(achievement_codes)} 个不重复成就代码")
            
            # 3. 插入成就目录
            for code in achievement_codes:
                cursor.execute(
                    "INSERT OR IGNORE INTO achievement_catalog (code) VALUES (?)",
                    (code,)
                )
            
            self.db_manager.get_connection().commit()
            self.logger.info("成就数据迁移完成")
            return True
            
        except Exception as e:
            self.logger.error(f"迁移成就数据失败: {e}", exc_info=True)
            return False
    
    def optimize_database_storage(self):
        """优化数据库存储"""
        self.logger.info("开始优化数据库存储...")
        
        conn = self.db_manager.get_connection()
        cursor = conn.cursor()
        
        try:
            # 1. 启用自动清理
            cursor.execute("PRAGMA auto_vacuum = FULL")
            
            # 2. 重建索引
            cursor.execute("ANALYZE")
            cursor.execute("REINDEX")
            
            # 3. 执行VACUUM
            self.logger.info("执行VACUUM...")
            conn.execute("VACUUM")
            
            conn.commit()
            self.logger.info("数据库优化完成")
            return True
            
        except Exception as e:
            self.logger.error(f"数据库优化失败: {e}")
            return False
    
    def get_database_stats(self):
        """获取数据库统计信息 - 修复版"""
        cursor = self.db_manager.get_connection().cursor()
        
        try:
            # 基础统计
            cursor.execute("SELECT COUNT(*) FROM player_profiles")
            profiles = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM player_titles")
            titles = cursor.fetchone()[0]
            
            # 成就相关统计
            cursor.execute("SELECT COUNT(*) FROM achievement_catalog")
            catalog = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM player_achievements")
            achievements = cursor.fetchone()[0]
            
            # 修复：使用子查询统计唯一成就关联数
            cursor.execute('''
            SELECT COUNT(*) FROM (
                SELECT DISTINCT uid, achievement_code FROM player_achievements
            )
            ''')
            unique_achievements = cursor.fetchone()[0]
            
            # 修复：统计唯一的成就类型
            cursor.execute("SELECT COUNT(DISTINCT achievement_code) FROM player_achievements")
            unique_achievement_types = cursor.fetchone()[0]
            
            # 平均每个玩家的成就数
            avg_achievements = achievements / profiles if profiles > 0 else 0
            
            # 获取数据库文件大小
            db_path = 'malody_rankings.db'
            db_size = 0
            try:
                if os.path.exists(db_path):
                    db_size = os.path.getsize(db_path) / 1024 / 1024  # 转换为MB
            except:
                pass
            
            # 获取更多详细统计
            cursor.execute("SELECT COUNT(DISTINCT uid) FROM player_achievements")
            players_with_achievements = cursor.fetchone()[0]
            
            # 获取最近爬取时间
            cursor.execute("SELECT MAX(last_crawled) FROM player_profiles")
            last_crawl_time = cursor.fetchone()[0]
            
            # 计算成就分布的统计
            cursor.execute('''
            SELECT 
                COUNT(*) as player_count,
                COUNT(*) * 100.0 / ? as percentage
            FROM (
                SELECT uid, COUNT(achievement_code) as achievement_count 
                FROM player_achievements 
                GROUP BY uid
            ) WHERE achievement_count >= 10
            ''', (profiles,))
            stats_10plus = cursor.fetchone()
            
            cursor.execute('''
            SELECT 
                COUNT(*) as player_count,
                COUNT(*) * 100.0 / ? as percentage
            FROM (
                SELECT uid, COUNT(achievement_code) as achievement_count 
                FROM player_achievements 
                GROUP BY uid
            ) WHERE achievement_count >= 5
            ''', (profiles,))
            stats_5plus = cursor.fetchone()
            
            return {
                'player_profiles': profiles,
                'player_titles': titles,
                'achievement_catalog': catalog,
                'achievement_records': achievements,
                'unique_achievement_associations': unique_achievements,
                'unique_achievement_types': unique_achievement_types,
                'players_with_achievements': players_with_achievements,
                'avg_achievements_per_player': round(avg_achievements, 2),
                'total_database_size_mb': round(db_size, 2),
                'last_crawl_time': last_crawl_time,
                'players_with_10plus_achievements': stats_10plus[0] if stats_10plus else 0,
                'players_with_10plus_percentage': round(stats_10plus[1], 2) if stats_10plus else 0,
                'players_with_5plus_achievements': stats_5plus[0] if stats_5plus else 0,
                'players_with_5plus_percentage': round(stats_5plus[1], 2) if stats_5plus else 0,
            }
            
        except Exception as e:
            self.logger.error(f"获取数据库统计失败: {e}", exc_info=True)
            return None

def signal_handler(sig, frame):
    """处理终止信号"""
    global stop_requested
    with stop_lock:
        stop_requested = True
    logging.getLogger().info("收到终止信号，正在安全退出...")
    time.sleep(1)
    sys.exit(0)

def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='玩家个人主页资料爬虫 - 优化版')
    
    # 爬取源选项
    source_group = parser.add_mutually_exclusive_group()
    source_group.add_argument('--uid', type=str, help='单个玩家UID')
    source_group.add_argument('--uid-list', type=str, help='逗号分隔的UID列表')
    source_group.add_argument('--uid-range', type=str, help='UID范围，格式: start-end (如: 1000-2000)')
    source_group.add_argument('--uid-file', type=str, help='包含UID列表的文件，每行一个')
    source_group.add_argument('--from-db', action='store_true', help='从数据库获取需要更新的玩家')
    source_group.add_argument('--from-leaderboard', action='store_true', help='从排行榜获取玩家')
    source_group.add_argument('--from-other-tables', action='store_true', 
                            help='从数据库其他表（player_identity, player_aliases等）提取UID')
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
    
    # 从其他表提取的选项
    parser.add_argument('--no-exclude-existing', action='store_true', 
                       help='从其他表提取时不排除已有玩家 (默认排除)')
    parser.add_argument('--no-priority-order', action='store_true', 
                       help='从其他表提取时不按优先级排序 (默认按最后出现时间倒序)')
    
    # 新增：数据库优化选项
    parser.add_argument('--cleanup-data', action='store_true', 
                       help='清理旧的数据结构')
    parser.add_argument('--migrate-achievements', action='store_true', 
                       help='迁移旧的成就数据到优化表')
    parser.add_argument('--optimize-db', action='store_true', 
                       help='优化数据库存储')
    parser.add_argument('--db-stats', action='store_true', 
                       help='显示详细的数据库统计信息')
    
    args = parser.parse_args()
    
    # 设置信号处理器
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # 设置日志
    log_level = getattr(logging, args.log_level)
    setup_detailed_logging(log_level=log_level, log_file=args.log_file)
    
    logger = logging.getLogger(__name__)
    logger.info("玩家个人主页爬虫启动（优化版），参数: %s", vars(args))
    
    # 初始化数据库（如果需要保存的话）
    if not args.print_only:
        init_database()
    
    # 创建爬虫实例
    crawler = PlayerProfileCrawler()
    
    # 数据库清理和优化选项
    if args.cleanup_data:
        logger.info("执行数据清理...")
        if crawler.cleanup_old_data():
            logger.info("数据清理成功")
        else:
            logger.error("数据清理失败")
        return
    
    if args.migrate_achievements:
        logger.info("执行成就数据迁移...")
        if crawler.migrate_achievements_data():
            logger.info("成就数据迁移成功")
        else:
            logger.error("成就数据迁移失败")
        return
    
    if args.optimize_db:
        logger.info("执行数据库优化...")
        if crawler.optimize_database_storage():
            logger.info("数据库优化成功")
        else:
            logger.error("数据库优化失败")
        return
    
    if args.db_stats:
        stats = crawler.get_database_stats()
        if stats:
            print("数据库详细统计 (优化版):")
            print("="*60)
            print(f"玩家资料数: {stats['player_profiles']:,}")
            print(f"头衔记录数: {stats['player_titles']:,}")
            print(f"成就目录数: {stats['achievement_catalog']:,}")
            print(f"成就关联记录: {stats['achievement_records']:,}")
            print(f"唯一成就关联: {stats['unique_achievement_associations']:,}")
            print(f"唯一成就类型: {stats['unique_achievement_types']:,}")
            print(f"有成就的玩家: {stats['players_with_achievements']:,} ({stats['players_with_achievements']/stats['player_profiles']*100:.1f}%)" if stats['player_profiles'] > 0 else "有成就的玩家: 0")
            print(f"平均成就数/玩家: {stats['avg_achievements_per_player']:.2f}")
            print(f"数据库总大小: {stats['total_database_size_mb']:.2f} MB")
            print(f"最后爬取时间: {stats['last_crawl_time']}")
            
            # 成就分布统计
            print("\n成就分布统计:")
            print("="*60)
            print(f"拥有5+个成就的玩家: {stats['players_with_5plus_achievements']:,} ({stats['players_with_5plus_percentage']}%)")
            print(f"拥有10+个成就的玩家: {stats['players_with_10plus_achievements']:,} ({stats['players_with_10plus_percentage']}%)")
            
            # 存储效率分析
            if stats['achievement_catalog'] > 0:
                compression_ratio = stats['unique_achievement_associations'] / stats['achievement_catalog']
                print(f"\n存储效率分析:")
                print("="*60)
                print(f"成就数据压缩比: {compression_ratio:.1f}:1")
                print(f"(每个成就被 {compression_ratio:.1f} 个玩家拥有)")
            
            # 建议
            if stats['avg_achievements_per_player'] == 0:
                print(f"\n⚠ 注意: 平均成就数为0，可能需要爬取成就数据")
            elif stats['total_database_size_mb'] > 500:
                print(f"\n⚠ 建议: 数据库文件较大，考虑运行 --optimize-db")
        else:
            print("获取数据库统计失败")
        return
    
    # 显示状态
    if args.status:
        if not args.print_only:
            cursor = crawler.db_manager.get_connection().cursor()
            
            # 玩家资料统计
            cursor.execute("SELECT COUNT(*) FROM player_profiles")
            profile_count = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM player_titles")
            title_count = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM achievement_catalog")
            catalog_count = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM player_achievements")
            achievement_count = cursor.fetchone()[0]
            
            # 修复：使用子查询统计唯一成就关联数
            cursor.execute('''
            SELECT COUNT(*) FROM (
                SELECT DISTINCT uid, achievement_code FROM player_achievements
            )
            ''')
            unique_achievement_associations = cursor.fetchone()[0]
            
            # 修复：使用子查询统计活跃玩家
            cursor.execute("SELECT COUNT(DISTINCT uid) FROM player_achievements")
            players_with_achievements = cursor.fetchone()[0]
            
            # 爬取状态统计
            cursor.execute("SELECT COUNT(*) FROM player_profiles WHERE last_crawled IS NULL")
            never_crawled = cursor.fetchone()[0]
            
            cursor.execute('''
            SELECT COUNT(*) FROM player_profiles 
            WHERE last_crawled < datetime('now', '-30 days')
            ''')
            outdated = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM player_profiles WHERE last_crawled >= datetime('now', '-1 day')")
            crawled_today = cursor.fetchone()[0]
            
            # 计算平均成就数
            avg_achievements = achievement_count / profile_count if profile_count > 0 else 0
            
            print("玩家资料数据库状态 (优化版):")
            print("="*60)
            print(f"玩家资料数: {profile_count:,}")
            print(f"头衔记录数: {title_count:,}")
            print(f"成就目录数: {catalog_count:,}")
            print(f"成就关联记录: {achievement_count:,}")
            print(f"唯一成就关联: {unique_achievement_associations:,}")
            print(f"有成就的玩家: {players_with_achievements:,} ({players_with_achievements/profile_count*100:.1f}%)")
            print(f"平均成就数/玩家: {avg_achievements:.2f}")
            print(f"\n爬取状态:")
            print(f"从未爬取: {never_crawled:,} ({never_crawled/profile_count*100:.1f}%)")
            print(f"已过期 (>30天): {outdated:,} ({outdated/profile_count*100:.1f}%)")
            print(f"今日爬取: {crawled_today:,} ({crawled_today/profile_count*100:.1f}%)")
            print(f"总计需更新: {never_crawled + outdated:,}")
            
            # 显示存储建议
            if achievement_count > 0:
                # 成就数据压缩比
                compression_ratio = unique_achievement_associations / catalog_count if catalog_count > 0 else 0
                print(f"\n存储效率:")
                print(f"成就数据压缩比: {compression_ratio:.1f}:1")
                print(f"(每个成就被 {compression_ratio:.1f} 个玩家拥有)")
                
                if avg_achievements > 10:
                    print(f"✓ 成就数据丰富，平均每个玩家有 {avg_achievements:.1f} 个成就")
                elif avg_achievements > 0:
                    print(f"⚠ 成就数据较少，平均每个玩家只有 {avg_achievements:.1f} 个成就")
                else:
                    print(f"✗ 没有成就数据，可能需要运行 --migrate-achievements")
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
    
    # 如果是仅打印模式，需要处理单个或多个UID
    if args.print_only and args.uid:
        # 单个UID的仅打印模式
        success = crawler.test_parse_and_print(args.uid.strip())
        return
    
    # 准备UID列表
    uid_list = []
    
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
        try:
            with open(args.uid_file, 'r', encoding='utf-8') as f:
                uid_list = [line.strip() for line in f if line.strip()]
        except Exception as e:
            logger.error("读取UID文件失败: %s", e)
            return
    
    elif args.from_other_tables:
        # 从数据库其他表中提取UID
        uid_list = crawler.crawl_from_other_tables(
            limit=args.limit,
            days_since_last_crawl=args.days_since_update,
            exclude_existing=not args.no_exclude_existing,
            priority_order=not args.no_priority_order
        )
    
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
    
    else:
        # 默认行为
        if not args.print_only:
            logger.info("未指定UID源，从数据库获取需要更新的玩家")
            uid_list = crawler.crawl_from_database(
                limit=args.limit or 100,
                days_since_last_crawl=args.days_since_update
            )
        else:
            logger.error("在 --print-only 模式下必须指定UID源 (--uid, --uid-list, --uid-range, --uid-file)")
            return
    
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
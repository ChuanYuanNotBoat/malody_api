import requests
from bs4 import BeautifulSoup
import pandas as pd
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
from collections import deque
import random

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
        log_file = f"logs/stb_crawler_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    
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
    logger.info("STB爬虫启动 - 详细日志已配置")
    logger.info("日志文件: %s", log_file)
    logger.info("日志级别: %s", logging.getLevelName(log_level))
    logger.info("=" * 80)
    
    return logger

# Malody API配置
BASE_URL = "https://m.mugzone.net"
HOMEPAGE_URL = BASE_URL + "/index"  # 主页URL
SEARCH_API_URL = BASE_URL + "/page/chart/filter"
CHART_URL = BASE_URL + "/chart/{cid}"
SONG_URL = BASE_URL + "/song/{sid}"

# 谱面状态映射
STATUS_MAP = {
    "Stable": 2,
    "Beta": 1, 
    "Alpha": 0
}

# 模式映射（复用现有的）
MODE_MAP = {
    0: "Key",
    1: "Step", 
    2: "DJ",
    3: "Catch",
    4: "Pad", 
    5: "Taiko",
    6: "Ring",
    7: "Slide",
    8: "Live",
    9: "Cube"
}

class STBCrawler:
    def __init__(self, session=None):
        # 首先设置日志
        self.setup_crawler_logging()
        
        if session is None:
            # 创建新的session并复用认证配置
            self.session = requests.Session()
            
            # 完全复制主爬虫的session配置
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
        
        # 用于跟踪已处理的谱面，避免重复
        self.processed_charts = set()
        self.processed_songs = set()
        
        # 失败重试队列
        self.retry_queue = deque()
        self.max_retries = 5  # 最大重试次数
        
    def setup_crawler_logging(self):
        """为爬虫设置专门的日志记录器"""
        self.logger = logging.getLogger('STBCrawler')
        
    def log_request_details(self, url, response, method="GET"):
        """记录请求的详细信息"""
        if response is not None:
            self.logger.debug(
                "请求详情 - 方法: %s, URL: %s, 状态码: %s, 内容长度: %s, 内容类型: %s",
                method, url, response.status_code, len(response.content), 
                response.headers.get('content-type', '未知')
            )
            
            # 如果是错误响应，记录更多信息
            if response.status_code >= 400:
                self.logger.warning(
                    "请求错误 - URL: %s, 状态码: %s, 响应头: %s, 响应内容前500字符: %s",
                    url, response.status_code, dict(response.headers), 
                    response.text[:500] if response.text else "空响应"
                )
        else:
            self.logger.warning("请求返回空响应 - URL: %s", url)
        
    def init_database(self):
        """初始化STB谱面相关的数据库表"""
        cursor = self.db_manager.get_connection().cursor()
        
        # 歌曲表
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS songs (
            sid INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            artist TEXT,
            bpm REAL,
            length INTEGER,
            cover_url TEXT,
            last_updated TIMESTAMP,
            crawl_time TIMESTAMP NOT NULL,
            data_hash TEXT
        )
        ''')
        
        # 谱面表
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS charts (
            cid INTEGER PRIMARY KEY,
            sid INTEGER NOT NULL,
            version TEXT NOT NULL,
            creator_uid INTEGER,
            creator_name TEXT,
            stabled_by_uid INTEGER,
            stabled_by_name TEXT,
            level TEXT,
            mode INTEGER NOT NULL,
            chart_length INTEGER,
            status INTEGER NOT NULL,
            heat INTEGER DEFAULT 0,
            love_count INTEGER DEFAULT 0,
            donate_count INTEGER DEFAULT 0,
            play_count INTEGER DEFAULT 0,
            last_updated TIMESTAMP,
            crawl_time TIMESTAMP NOT NULL,
            data_hash TEXT,
            FOREIGN KEY (sid) REFERENCES songs (sid)
        )
        ''')
        
        # 爬虫状态表
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS stb_crawler_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            last_crawl_time TIMESTAMP,
            last_chart_cid INTEGER
        )
        ''')
        
        # 创建索引
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_charts_sid ON charts(sid)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_charts_mode ON charts(mode)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_charts_status ON charts(status)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_charts_last_updated ON charts(last_updated)')
        
        # 检查并添加缺失的列
        self._check_and_add_missing_columns()
        
        self.db_manager.get_connection().commit()
        self.logger.info("STB谱面数据库表初始化完成")

    def _check_and_add_missing_columns(self):
        """检查并添加缺失的列"""
        cursor = self.db_manager.get_connection().cursor()
        
        try:
            # 检查songs表是否有data_hash列
            cursor.execute("PRAGMA table_info(songs)")
            columns = [column[1] for column in cursor.fetchall()]
            
            if 'data_hash' not in columns:
                # 先尝试添加不带UNIQUE约束的列
                cursor.execute('ALTER TABLE songs ADD COLUMN data_hash TEXT')
                self.logger.info("已添加data_hash列到songs表")
            
            # 检查charts表是否有data_hash列
            cursor.execute("PRAGMA table_info(charts)")
            columns = [column[1] for column in cursor.fetchall()]
            
            if 'data_hash' not in columns:
                cursor.execute('ALTER TABLE charts ADD COLUMN data_hash TEXT')
                self.logger.info("已添加data_hash列到charts表")
                
        except Exception as e:
            self.logger.warning("检查表结构时出错: %s", e)

    def test_connection(self):
        """测试连接和认证 - 使用与主爬虫相同的方式"""
        self.logger.info("开始连接测试...")
        
        try:
            # 测试访问排行榜页面（与主爬虫相同）
            test_url = BASE_URL + "/page/all/player?from=0&mode=0"
            self.logger.debug("测试连接: %s", test_url)
            response = self.session.get(test_url, timeout=30)
            response.raise_for_status()
            
            self.log_request_details(test_url, response)
            self.logger.info("✓ 排行榜页面访问正常")
            
            # 测试访问主页
            self.logger.debug("测试主页: %s", HOMEPAGE_URL)
            response = self.session.get(HOMEPAGE_URL, timeout=30)
            response.raise_for_status()
            
            self.log_request_details(HOMEPAGE_URL, response)
            self.logger.info("✓ 主页访问正常")
            
            self.logger.info("连接测试全部通过")
            return True
            
        except requests.exceptions.RequestException as e:
            self.logger.error("连接测试失败: %s", e)
            if hasattr(e, 'response') and e.response is not None:
                self.log_request_details(getattr(e, 'url', '未知'), e.response)
            
            self.logger.info("尝试备用连接测试...")
            return self.fallback_connection_test()
    
    def fallback_connection_test(self):
        """备用连接测试方法"""
        try:
            # 只测试基础连接
            response = self.session.get(BASE_URL, timeout=30)
            response.raise_for_status()
            self.logger.info("备用连接测试成功")
            return True
        except Exception as e:
            self.logger.error("备用连接测试也失败: %s", e)
            return False

    def search_charts(self, mode=None, status=2, count=18, page=0, key="", creator=""):
        """搜索谱面API"""
        params = {
            "status": status,
            "count": count,
            "page": page,
            "key": key,
            "creator": creator
        }
        
        if mode is not None:
            params["mode"] = mode
            
        self.logger.info("搜索谱面 - 模式: %s, 状态: %s, 页数: %s", mode, status, page)
        self.logger.debug("搜索参数: %s", params)
        
        try:
            # 添加CSRF token到表单数据
            data = params.copy()
            if 'csrftoken' in COOKIES:
                data['csrfmiddlewaretoken'] = COOKIES['csrftoken']
                self.logger.debug("添加CSRF token")
            
            # API请求headers
            api_headers = {
                "Content-Type": "application/x-www-form-urlencoded",
                "X-Requested-With": "XMLHttpRequest",
                "Origin": BASE_URL
            }
            
            self.logger.debug("发送API请求到: %s", SEARCH_API_URL)
            response = self.session.post(SEARCH_API_URL, data=data, headers=api_headers, timeout=30)
            response.raise_for_status()
            
            self.log_request_details(SEARCH_API_URL, response, "POST")
            
            # 检查响应内容类型
            content_type = response.headers.get('content-type', '')
            self.logger.debug("响应内容类型: %s", content_type)
            
            if 'application/json' in content_type:
                result = response.json()
                self.logger.info("API搜索成功 - 获取到 %d 个谱面", len(result.get("list", [])))
                self.logger.debug("API响应: %s", result)
                return result
            else:
                self.logger.warning("API返回非JSON响应: %s", content_type)
                self.logger.debug("响应内容前1000字符: %s", response.text[:1000])
                return None
                
        except requests.exceptions.RequestException as e:
            self.logger.error("搜索谱面失败: %s", e)
            if hasattr(e, 'response') and e.response is not None:
                self.log_request_details(SEARCH_API_URL, e.response, "POST")
            return None

    def parse_chart_page(self, html, cid):
        """增强的谱面页面解析，确保能提取SID"""
        self.logger.info("开始解析谱面页面: cid=%s", cid)
        
        soup = BeautifulSoup(html, "html.parser")
        
        # 提取基础信息
        chart_data = {
            "cid": cid,
            "version": "",
            "creator_uid": None,
            "creator_name": "",
            "stabled_by_uid": None, 
            "stabled_by_name": "",
            "level": "",
            "mode": 0,
            "chart_length": 0,
            "status": 0,
            "heat": 0,
            "love_count": 0,
            "donate_count": 0,
            "play_count": 0,
            "last_updated": None
        }
        
        song_data = {
            "sid": None,
            "title": "",
            "artist": "",
            "bpm": 0,
            "length": 0,
            "cover_url": ""
        }
        
        try:
            # 方法1: 从JavaScript变量中提取SID
            script_text = soup.find('script', string=re.compile('window\.malody'))
            if script_text:
                # 查找sid
                sid_match = re.search(r'sid\s*:\s*(\d+)', script_text.string)
                if sid_match:
                    song_data["sid"] = int(sid_match.group(1))
                    self.logger.debug("从JS提取到SID: %s", song_data["sid"])
            
            # 方法2: 从封面URL提取SID
            if not song_data["sid"]:
                cover_div = soup.select_one('.song_title .cover')
                if cover_div and 'style' in cover_div.attrs:
                    style = cover_div['style']
                    url_match = re.search(r'url\((.*?)\)', style)
                    if url_match:
                        cover_url = url_match.group(1)
                        song_data["cover_url"] = cover_url
                        # 从封面URL提取SID
                        sid_match = re.search(r'/(\d+)!', cover_url)
                        if sid_match:
                            song_data["sid"] = int(sid_match.group(1))
                            self.logger.debug("从封面URL提取SID: %s", song_data["sid"])
            
            # 方法3: 从页面链接中提取SID
            if not song_data["sid"]:
                for link in soup.find_all('a', href=True):
                    href = link['href']
                    if '/song/' in href:
                        sid_match = re.search(r'/song/(\d+)', href)
                        if sid_match:
                            song_data["sid"] = int(sid_match.group(1))
                            self.logger.debug("从链接提取SID: %s", song_data["sid"])
                            break
            
            # 方法4: 从面包屑导航或其他元素中提取
            if not song_data["sid"]:
                # 查找包含歌曲ID的元素
                sid_elements = soup.find_all(text=re.compile(r'[Ss]ong[ _-]?[IiDd]'))
                for element in sid_elements:
                    sid_match = re.search(r'(\d+)', element)
                    if sid_match:
                        song_data["sid"] = int(sid_match.group(1))
                        self.logger.debug("从文本提取SID: %s", song_data["sid"])
                        break
            
            # 如果仍然没有SID，记录详细信息用于调试
            if not song_data["sid"]:
                self.logger.warning("无法提取SID (cid=%s)，保存页面用于分析", cid)
                debug_file = f"logs/debug_cid_{cid}_no_sid.html"
                with open(debug_file, 'w', encoding='utf-8') as f:
                    f.write(html)
                self.logger.info("已保存页面到: %s", debug_file)
            
            # 记录页面基本信息
            title_tag = soup.select_one('title')
            if title_tag:
                self.logger.debug("页面标题: %s", title_tag.get_text())
            
            # 从JavaScript变量中提取cid
            if script_text:
                cid_match = re.search(r'cid:(\d+)', script_text.string)
                if cid_match:
                    chart_data["cid"] = int(cid_match.group(1))
                    self.logger.debug("从JS提取到CID: %s", chart_data["cid"])
            else:
                self.logger.debug("未找到window.malody脚本")
            
            # 修复：提取状态 - 同时检查t1和t2类
            status_tag = None
            # 先尝试t1类（Beta状态使用）
            status_tag = soup.select_one('.song_title .title em.t1')
            # 如果没有找到t1，尝试t2类（Stable状态使用）
            if not status_tag:
                status_tag = soup.select_one('.song_title .title em.t2')
            # 如果还没有找到，尝试查找任何em标签
            if not status_tag:
                status_tag = soup.select_one('.song_title .title em')
            
            if status_tag:
                status_text = status_tag.get_text().strip()
                chart_data["status"] = STATUS_MAP.get(status_text, 0)
                self.logger.debug("提取状态: %s -> %s", status_text, chart_data["status"])
            else:
                self.logger.debug("未找到状态标签")
                # 尝试从其他位置查找状态信息
                status_elements = soup.find_all('em', class_=re.compile(r't[12]'))
                for elem in status_elements:
                    status_text = elem.get_text().strip()
                    if status_text in STATUS_MAP:
                        chart_data["status"] = STATUS_MAP[status_text]
                        self.logger.debug("从备选位置提取状态: %s -> %s", status_text, chart_data["status"])
                        break
            
            # 提取标题和艺术家
            title_tag = soup.select_one('.song_title .title')
            if title_tag:
                # 提取艺术家
                artist_span = title_tag.find('span', class_='artist')
                if artist_span:
                    song_data["artist"] = artist_span.get_text().strip()
                    self.logger.debug("提取艺术家: %s", song_data["artist"])
                    artist_span.decompose()
                else:
                    self.logger.debug("未找到艺术家标签")
                
                # 移除状态标签
                for em in title_tag.find_all('em'):
                    em.decompose()
                
                # 提取标题文本
                title_text = title_tag.get_text().strip()
                if title_text.startswith(' - '):
                    title_text = title_text[3:].strip()
                song_data["title"] = title_text
                self.logger.debug("提取标题: %s", song_data["title"])
            else:
                self.logger.warning("未找到标题区域")
            
            # 提取版本和模式
            mode_tag = soup.select_one('.song_title .mode')
            if mode_tag:
                version_spans = mode_tag.find_all('span')
                if version_spans:
                    chart_data["version"] = version_spans[0].get_text().strip()
                    self.logger.debug("提取版本: %s", chart_data["version"])
                
                # 提取模式
                img_tag = mode_tag.find('img')
                if img_tag and 'src' in img_tag.attrs:
                    src = img_tag['src']
                    mode_match = re.search(r'mode-(\d+)', src)
                    if mode_match:
                        chart_data["mode"] = int(mode_match.group(1))
                        self.logger.debug("提取模式: %s", chart_data["mode"])
                else:
                    self.logger.debug("未找到模式图片")
                
                # 提取等级
                version_text = chart_data["version"]
                level_match = re.search(r'Lv\.(\d+(?:\.\d+)?)', version_text)
                if level_match:
                    chart_data["level"] = level_match.group(1)
                    self.logger.debug("提取等级: %s", chart_data["level"])
            else:
                self.logger.debug("未找到模式区域")
            
            # 提取创作者信息
            created_by_spans = [span for span in soup.find_all('span') 
                            if span.get_text().strip().startswith('Created by:')]
            
            if created_by_spans:
                created_by_span = created_by_spans[0]
                # 查找紧随其后的创作者链接
                creator_link = None
                for sibling in created_by_span.next_siblings:
                    if hasattr(sibling, 'name') and sibling.name == 'a':
                        creator_link = sibling
                        break
                
                if creator_link and 'href' in creator_link.attrs:
                    href = creator_link['href']
                    uid_match = re.search(r'/accounts/user/(\d+)', href)
                    if uid_match:
                        chart_data["creator_uid"] = int(uid_match.group(1))
                        chart_data["creator_name"] = creator_link.get_text().strip()
                        self.logger.debug("提取创作者: %s (UID: %s)", 
                                        chart_data["creator_name"], chart_data["creator_uid"])
            else:
                self.logger.debug("未找到创作者信息")
            
            # 提取稳定者信息
            stabled_by_spans = [span for span in soup.find_all('span') 
                            if span.get_text().strip().startswith('Stabled by:')]
            
            if stabled_by_spans:
                stabled_by_span = stabled_by_spans[0]
                # 查找紧随其后的稳定者链接
                stabled_link = None
                for sibling in stabled_by_span.next_siblings:
                    if hasattr(sibling, 'name') and sibling.name == 'a':
                        stabled_link = sibling
                        break
                
                if stabled_link and 'href' in stabled_link.attrs:
                    href = stabled_link['href']
                    uid_match = re.search(r'/accounts/user/(\d+)', href)
                    if uid_match:
                        chart_data["stabled_by_uid"] = int(uid_match.group(1))
                        chart_data["stabled_by_name"] = stabled_link.get_text().strip()
                        self.logger.debug("提取稳定者: %s (UID: %s)", 
                                        chart_data["stabled_by_name"], chart_data["stabled_by_uid"])
            else:
                self.logger.debug("未找到稳定者信息")
            
            # 提取ID、长度、BPM、最后更新时间
            sub_tag = soup.select_one('.song_title .sub')
            if sub_tag:
                sub_text = sub_tag.get_text()
                
                # 使用正则表达式提取所有信息
                # ID
                id_match = re.search(r'ID\s*:c?(\d+)', sub_text)
                if id_match:
                    chart_data["cid"] = int(id_match.group(1))
                    self.logger.debug("提取CID: %s", chart_data["cid"])
                
                # 长度 - 修复：使用英文"Length"而不是中文"长度"
                length_match = re.search(r'Length\s*:\s*(\d+)s', sub_text)
                if length_match:
                    length_value = int(length_match.group(1))
                    chart_data["chart_length"] = length_value
                    song_data["length"] = length_value
                    self.logger.debug("提取长度: %s秒", length_value)
                
                # BPM
                bpm_match = re.search(r'BPM\s*:\s*(\d+(?:\.\d+)?)', sub_text)
                if bpm_match:
                    try:
                        song_data["bpm"] = float(bpm_match.group(1))
                        self.logger.debug("提取BPM: %s", song_data["bpm"])
                    except ValueError:
                        self.logger.warning("无法解析BPM值: %s", bpm_match.group(1))
                
                # 最后更新时间 - 修复：使用英文"Last updated"而不是中文"最后更新"
                date_match = re.search(r'Last updated\s*:\s*(\d{4}-\d{2}-\d{2} \d{2}:\d{2})', sub_text)
                if date_match:
                    try:
                        chart_data["last_updated"] = datetime.strptime(date_match.group(1), "%Y-%m-%d %H:%M")
                        self.logger.debug("提取最后更新时间: %s", chart_data["last_updated"])
                    except ValueError:
                        self.logger.warning("无法解析日期: %s", date_match.group(1))
            else:
                self.logger.debug("未找到详细信息区域")
            
            # 提取热度信息 - 修复：正确解析字段映射
            like_area = soup.select_one('.like_area')
            if like_area:
                # 查找所有包含数字的div
                num_divs = like_area.find_all('div', class_='num')
                
                for div in num_divs:
                    div_text = div.get_text().strip()
                    value_span = div.find('span', class_='l')
                    
                    if value_span:
                        try:
                            value = int(value_span.get_text().strip())
                            
                            # 根据div内容判断字段类型
                            if 'Donation' in div_text:
                                chart_data["donate_count"] = value
                                self.logger.debug("提取打赏数: %s", value)
                            elif 'Hot' in div_text:
                                chart_data["heat"] = value
                                self.logger.debug("提取热度: %s", value)
                            elif 'N/A' not in div_text and not any(keyword in div_text for keyword in ['Donation', 'Hot']):
                                # 可能是爱心数量
                                chart_data["love_count"] = value
                                self.logger.debug("提取爱心数: %s", value)
                        except ValueError:
                            self.logger.debug("无法解析数字: %s", value_span.get_text().strip())
            else:
                self.logger.debug("未找到热度区域")
            
            # 如果还没有sid，记录警告
            if not song_data["sid"]:
                self.logger.warning("无法提取歌曲ID (cid=%s)", cid)
            
            # 记录解析结果
            self.logger.info("解析完成 - 标题: %s, 艺术家: %s, SID: %s, 模式: %s, 状态: %s", 
                        song_data["title"], song_data["artist"], song_data["sid"], 
                        chart_data["mode"], chart_data["status"])
            
            return chart_data, song_data
            
        except Exception as e:
            self.logger.error("解析谱面页面失败 (cid=%s): %s", cid, e, exc_info=True)
            return None, None

    def crawl_chart_detail(self, cid):
        """爬取单个谱面的详细信息"""
        url = CHART_URL.format(cid=cid)
        self.logger.info("开始爬取谱面详情: cid=%s, url=%s", cid, url)
        
        # 检查是否已处理过
        if cid in self.processed_charts:
            self.logger.debug("谱面 %s 已处理过，跳过", cid)
            return True
        
        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            
            self.log_request_details(url, response)
            
            # 检查页面内容
            if len(response.content) < 100:
                self.logger.warning("页面内容过短，可能为空页面: %s", len(response.content))
                return False
            
            chart_data, song_data = self.parse_chart_page(response.text, cid)
            if chart_data and song_data:
                self.logger.info("解析成功，准备保存数据: cid=%s", cid)
                success = self.save_chart_data(chart_data, song_data)
                if success:
                    self.processed_charts.add(cid)
                    if song_data["sid"]:
                        self.processed_songs.add(song_data["sid"])
                return success
            else:
                self.logger.warning("解析谱面页面返回空数据 (cid=%s)", cid)
                # 保存页面内容用于调试
                debug_file = f"logs/debug_cid_{cid}.html"
                with open(debug_file, 'w', encoding='utf-8') as f:
                    f.write(response.text)
                self.logger.info("已保存页面内容到: %s", debug_file)
                return False
                
        except requests.exceptions.RequestException as e:
            self.logger.error("爬取谱面详情失败 (cid=%s): %s", cid, e)
            if hasattr(e, 'response') and e.response is not None:
                self.log_request_details(url, e.response)
            return False

    def crawl_chart_detail_with_retry(self, cid, retry_count=0):
        """爬取单个谱面详情，支持重试机制"""
        if retry_count >= self.max_retries:
            self.logger.warning("CID %d 已达到最大重试次数 %d，放弃爬取", cid, self.max_retries)
            return False
        
        url = CHART_URL.format(cid=cid)
        
        try:
            response = self.session.get(url, timeout=30)
            
            # 检查响应状态
            if response.status_code == 404:
                self.logger.info("CID %d 返回404，谱面不存在", cid)
                return None  # 明确表示谱面不存在
            
            response.raise_for_status()
            
            # 检查页面内容是否有效
            if len(response.content) < 100:
                self.logger.warning("CID %d 页面内容过短，可能无效", cid)
                raise Exception("页面内容过短")
            
            chart_data, song_data = self.parse_chart_page(response.text, cid)
            if chart_data and song_data:
                success = self.save_chart_data(chart_data, song_data)
                if success:
                    self.processed_charts.add(cid)
                    if song_data["sid"]:
                        self.processed_songs.add(song_data["sid"])
                    return True
            else:
                raise Exception("解析返回空数据")
                
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                self.logger.info("CID %d 返回404，谱面不存在", cid)
                return None
            else:
                self.logger.warning("CID %d HTTP错误 (重试 %d/%d): %s", 
                                  cid, retry_count + 1, self.max_retries, e)
                # 添加到重试队列
                self.retry_queue.append((cid, retry_count + 1))
                return False
                
        except (requests.exceptions.RequestException, Exception) as e:
            self.logger.warning("CID %d 爬取失败 (重试 %d/%d): %s", 
                              cid, retry_count + 1, self.max_retries, e)
            # 添加到重试队列
            self.retry_queue.append((cid, retry_count + 1))
            return False
        
        return False

    def process_retry_queue(self, delay_between_retries=10):
        """处理重试队列中的失败请求"""
        if not self.retry_queue:
            return 0
        
        self.logger.info("开始处理重试队列，共有 %d 个失败请求", len(self.retry_queue))
        success_count = 0
        
        # 复制队列以避免在迭代时修改
        retry_items = list(self.retry_queue)
        self.retry_queue.clear()
        
        for cid, retry_count in retry_items:
            if stop_requested:
                break
                
            self.logger.info("重试 CID %d (第 %d 次重试)", cid, retry_count + 1)
            
            # 重试间隔
            time.sleep(delay_between_retries)
            
            result = self.crawl_chart_detail_with_retry(cid, retry_count)
            if result is True:  # 明确成功
                success_count += 1
        
        self.logger.info("重试队列处理完成: 成功 %d/%d", success_count, len(retry_items))
        return success_count

    def generate_data_hash(self, data):
        """生成数据的哈希值用于去重"""
        data_str = json.dumps(data, sort_keys=True, default=str)
        return hashlib.md5(data_str.encode('utf-8')).hexdigest()

    def save_chart_data(self, chart_data, song_data):
        """保存谱面数据到数据库 - 覆盖更新模式，如果封面缺失则保留原来的封面"""
        cursor = self.db_manager.get_connection().cursor()
        crawl_time = datetime.now()
        
        try:
            # 检查必要的数据是否存在
            if not song_data["sid"]:
                self.logger.error("缺少歌曲ID，无法保存数据 (cid=%s)", chart_data["cid"])
                return False
            
            # 生成数据哈希
            song_hash = self.generate_data_hash(song_data)
            chart_hash = self.generate_data_hash(chart_data)
            
            # 记录保存的数据详情
            self.logger.info("保存数据详情 - 谱面: %s, 歌曲: %s, 标题: %s, 艺术家: %s, 模式: %s, 状态: %s", 
                           chart_data["cid"], song_data["sid"], song_data["title"], 
                           song_data["artist"], chart_data["mode"], chart_data["status"])
            
            # 检查歌曲是否已存在，如果存在且新封面为空，则使用原来的封面
            existing_cover_url = None
            if not song_data["cover_url"]:
                cursor.execute("SELECT cover_url FROM songs WHERE sid = ?", (song_data["sid"],))
                result = cursor.fetchone()
                if result and result[0]:
                    existing_cover_url = result[0]
                    self.logger.info("封面为空，使用数据库中已有的封面: %s", existing_cover_url)
            
            # 保存歌曲信息 - 使用 REPLACE 覆盖更新
            final_cover_url = song_data["cover_url"] if song_data["cover_url"] else existing_cover_url
            
            cursor.execute('''
            INSERT OR REPLACE INTO songs 
            (sid, title, artist, bpm, length, cover_url, last_updated, crawl_time, data_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                song_data["sid"], song_data["title"], song_data["artist"], 
                song_data["bpm"], song_data["length"], final_cover_url,
                chart_data["last_updated"], crawl_time, song_hash
            ))
            
            # 保存谱面信息 - 使用 REPLACE 覆盖更新
            cursor.execute('''
            INSERT OR REPLACE INTO charts 
            (cid, sid, version, creator_uid, creator_name, stabled_by_uid, stabled_by_name,
             level, mode, chart_length, status, heat, love_count, donate_count, play_count,
             last_updated, crawl_time, data_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                chart_data["cid"], song_data["sid"], chart_data["version"],
                chart_data["creator_uid"], chart_data["creator_name"],
                chart_data["stabled_by_uid"], chart_data["stabled_by_name"],
                chart_data["level"], chart_data["mode"], chart_data["chart_length"],
                chart_data["status"], chart_data["heat"], chart_data["love_count"],
                chart_data["donate_count"], chart_data["play_count"],
                chart_data["last_updated"], crawl_time, chart_hash
            ))
            
            self.logger.info("✓ 保存/更新谱面: %s - %s", chart_data["cid"], song_data["title"])
            self.db_manager.get_connection().commit()
            return True
            
        except Exception as e:
            self.logger.error("保存谱面数据失败 (cid=%s): %s", chart_data["cid"], e)
            self.db_manager.get_connection().rollback()
            return False

    def get_last_crawl_state(self):
        """获取最后爬取状态"""
        cursor = self.db_manager.get_connection().cursor()
        cursor.execute("SELECT last_crawl_time, last_chart_cid FROM stb_crawler_state WHERE id = 1")
        result = cursor.fetchone()
        
        if result:
            return {
                "last_crawl_time": result[0],
                "last_chart_cid": result[1]
            }
        else:
            # 默认返回一周前
            one_week_ago = datetime.now() - timedelta(days=7)
            return {
                "last_crawl_time": one_week_ago,
                "last_chart_cid": None
            }

    def update_crawl_state(self, last_crawl_time=None, last_chart_cid=None):
        """更新爬取状态"""
        cursor = self.db_manager.get_connection().cursor()
        
        if last_crawl_time is None:
            last_crawl_time = datetime.now()
        
        cursor.execute('''
        INSERT OR REPLACE INTO stb_crawler_state 
        (id, last_crawl_time, last_chart_cid)
        VALUES (1, ?, ?)
        ''', (last_crawl_time, last_chart_cid))
        
        self.db_manager.get_connection().commit()

    def crawl_from_homepage(self, max_charts=50):
        """从主页爬取新上架谱面"""
        self.logger.info("=== 开始方式1: 从主页爬取新谱面 ===")
        self.logger.info("最大爬取数量: %d", max_charts)
        
        try:
            self.logger.debug("访问主页: %s", HOMEPAGE_URL)
            response = self.session.get(HOMEPAGE_URL, timeout=30)
            response.raise_for_status()
            
            self.log_request_details(HOMEPAGE_URL, response)
            
            soup = BeautifulSoup(response.text, "html.parser")
            
            # 查找新谱上架区域
            new_map_section = soup.find('div', id='newMap')
            if not new_map_section:
                self.logger.warning("未找到新谱上架区域 (id=newMap)")
                # 保存页面用于调试
                with open("logs/debug_homepage.html", 'w', encoding='utf-8') as f:
                    f.write(response.text)
                self.logger.info("已保存主页内容到 logs/debug_homepage.html")
                return 0
            
            # 查找所有谱面卡片
            chart_cards = new_map_section.find_all('div', class_='g_map')
            self.logger.info("在主页找到 %d 个新谱面卡片", len(chart_cards))
            
            if not chart_cards:
                self.logger.warning("新谱上架区域中没有找到谱面卡片")
                return 0
            
            success_count = 0
            crawled_songs = set()
            
            for i, card in enumerate(chart_cards):
                if stop_requested:
                    self.logger.info("爬取被中断")
                    break
                    
                if success_count >= max_charts:
                    self.logger.info("达到最大爬取数量: %d", max_charts)
                    break
                
                self.logger.debug("处理第 %d/%d 个谱面卡片", i+1, len(chart_cards))
                
                # 提取歌曲链接
                song_link = card.find('a', class_='link', href=True)
                if not song_link:
                    self.logger.debug("卡片 %d 未找到歌曲链接", i+1)
                    continue
                    
                song_url = song_link['href']
                self.logger.debug("找到歌曲链接: %s", song_url)
                
                if not song_url.startswith('/song/'):
                    self.logger.debug("卡片 %d 的链接不是歌曲链接: %s", i+1, song_url)
                    continue
                
                # 提取歌曲ID
                sid_match = re.search(r'/song/(\d+)', song_url)
                if not sid_match:
                    self.logger.debug("卡片 %d 无法提取歌曲ID: %s", i+1, song_url)
                    continue
                    
                sid = int(sid_match.group(1))
                self.logger.debug("提取到歌曲ID: %s", sid)
                
                # 避免重复爬取同一歌曲
                if sid in crawled_songs or sid in self.processed_songs:
                    self.logger.debug("歌曲 %d 已处理过，跳过", sid)
                    continue
                crawled_songs.add(sid)
                
                self.logger.info("处理歌曲 %d (%d/%d)", sid, i+1, len(chart_cards))
                
                # 从歌曲页面获取所有谱面
                song_cids = self.get_charts_from_song_page(sid)
                if song_cids:
                    self.logger.info("歌曲 %d 有 %d 个谱面: %s", sid, len(song_cids), song_cids)
                    
                    for j, cid in enumerate(song_cids):
                        if stop_requested:
                            break
                            
                        if success_count >= max_charts:
                            break
                            
                        self.logger.info("爬取谱面 %d/%d: cid=%s", j+1, len(song_cids), cid)
                        
                        if self.crawl_chart_detail(cid):
                            success_count += 1
                            self.logger.info("✓ 成功爬取谱面 %s (进度: %d/%d)", cid, success_count, max_charts)
                        else:
                            self.logger.warning("✗ 爬取谱面 %s 失败", cid)
                        
                        time.sleep(1)
                else:
                    self.logger.warning("歌曲 %d 没有找到谱面", sid)
            
            self.logger.info("方式1完成: 成功 %d/%d 个谱面", success_count, max_charts)
            return success_count
            
        except Exception as e:
            self.logger.error("从主页爬取失败: %s", e, exc_info=True)
            return 0

    def get_charts_from_song_page(self, sid):
        """增强的歌曲页面CID获取"""
        url = SONG_URL.format(sid=sid)
        cids = set()
        
        try:
            self.logger.debug("访问歌曲页面: %s", url)
            response = self.session.get(url, timeout=30)
            
            # 检查页面是否存在
            if response.status_code == 404:
                self.logger.debug("SID %d 不存在 (404)", sid)
                return []
            
            response.raise_for_status()
            
            # 方法1: 正则匹配所有chart链接
            pattern = r'/chart/(\d+)'
            matches = re.findall(pattern, response.text)
            for match in matches:
                cids.add(int(match))
            
            # 方法2: 从表格中提取
            soup = BeautifulSoup(response.text, "html.parser")
            
            # 查找所有包含谱面链接的元素
            for link in soup.find_all('a', href=True):
                href = link['href']
                if '/chart/' in href:
                    cid_match = re.search(r'/chart/(\d+)', href)
                    if cid_match:
                        cids.add(int(cid_match.group(1)))
            
            # 方法3: 从JavaScript数据中提取
            script_text = soup.find('script', string=re.compile('cid'))
            if script_text:
                cid_matches = re.findall(r'cid[\'"]?\s*:\s*[\'"]?(\d+)', script_text.string)
                for match in cid_matches:
                    cids.add(int(match))
            
            self.logger.info("从SID %d 提取到 %d 个CID", sid, len(cids))
            return list(cids)
            
        except requests.exceptions.RequestException as e:
            self.logger.warning("访问SID %d 失败: %s", sid, e)
            return []
        except Exception as e:
            self.logger.error("解析SID %d 页面时出错: %s", sid, e)
            return []

    def crawl_from_latest_page(self, max_charts=100):
        """从最近变动页面爬取谱面"""
        self.logger.info("=== 开始方式2: 从最近变动页面爬取 ===")
        self.logger.info("最大爬取数量: %d", max_charts)
        
        latest_url = BASE_URL + "/page/latest"
        try:
            self.logger.debug("访问最近变动页面: %s", latest_url)
            response = self.session.get(latest_url, timeout=30)
            response.raise_for_status()
            
            self.log_request_details(latest_url, response)
            
            soup = BeautifulSoup(response.text, "html.parser")
            
            # 查找所有包含谱面信息的元素
            chart_links = []
            for link in soup.find_all('a', href=True):
                href = link['href']
                if '/chart/' in href:
                    chart_links.append(href)
            
            # 从链接中提取CID
            cids = set()
            for link in chart_links:
                cid_match = re.search(r'/chart/(\d+)', link)
                if cid_match:
                    cid = int(cid_match.group(1))
                    cids.add(cid)
            
            self.logger.info("从最近变动页面找到 %d 个可能的谱面ID", len(cids))
            
            # 限制爬取数量并过滤已处理的
            cids_to_crawl = []
            for cid in list(cids)[:max_charts]:
                if cid not in self.processed_charts:
                    cids_to_crawl.append(cid)
            
            self.logger.info("实际需要爬取的谱面: %d 个 (过滤掉已处理的)", len(cids_to_crawl))
            
            success_count = 0
            for i, cid in enumerate(cids_to_crawl):
                if stop_requested:
                    break
                    
                self.logger.info("爬取谱面 %d/%d: cid=%s", i+1, len(cids_to_crawl), cid)
                
                if self.crawl_chart_detail(cid):
                    success_count += 1
                    self.logger.info("✓ 成功爬取谱面 %s (进度: %d/%d)", cid, success_count, len(cids_to_crawl))
                else:
                    self.logger.warning("✗ 爬取谱面 %s 失败", cid)
                
                time.sleep(1)  # 避免请求过于频繁
            
            self.logger.info("方式2完成: 成功 %d/%d 个谱面", success_count, len(cids_to_crawl))
            return success_count
            
        except Exception as e:
            self.logger.error("从最近变动页面爬取失败: %s", e, exc_info=True)
            return 0

    def crawl_from_api_search(self, modes=None, statuses=None, max_charts=50):
        """通过API搜索爬取谱面"""
        self.logger.info("=== 开始方式3: 通过API搜索爬取 ===")
        
        if modes is None:
            modes = [0]  # 默认Key模式
        if statuses is None:
            statuses = [2]  # 默认Stable状态
        
        self.logger.info("搜索模式: %s, 状态: %s, 最大爬取数量: %d", modes, statuses, max_charts)
        
        success_count = 0
        
        for mode in modes:
            for status in statuses:
                if stop_requested:
                    self.logger.info("爬取被中断")
                    break
                    
                if success_count >= max_charts:
                    self.logger.info("达到最大爬取数量: %d", max_charts)
                    break
                    
                self.logger.info("尝试API搜索: 模式 %d, 状态 %d", mode, status)
                page = 0
                has_more = True
                
                while has_more and not stop_requested and success_count < max_charts:
                    result = self.search_charts(mode=mode, status=status, page=page)
                    if not result or "list" not in result:
                        self.logger.warning("模式 %d 状态 %d 第 %d 页无数据或请求失败", mode, status, page)
                        break
                    
                    chart_list = result["list"]
                    if not chart_list:
                        self.logger.info("模式 %d 状态 %d 第 %d 页无数据，结束该模式", mode, status, page)
                        break
                    
                    self.logger.info("模式 %d 状态 %d 第 %d 页获取到 %d 个谱面", 
                                   mode, status, page, len(chart_list))
                    
                    for i, chart in enumerate(chart_list):
                        if stop_requested:
                            break
                            
                        if success_count >= max_charts:
                            break
                            
                        cid = chart.get("id")
                        if not cid:
                            continue
                            
                        self.logger.info("爬取谱面 %d/%d: cid=%s", i+1, len(chart_list), cid)
                        
                        # 爬取谱面详情
                        if self.crawl_chart_detail(cid):
                            success_count += 1
                            self.logger.info("✓ 成功爬取谱面 %s (进度: %d/%d)", cid, success_count, max_charts)
                        else:
                            self.logger.warning("✗ 爬取谱面 %s 失败", cid)
                        
                        # 避免请求过于频繁
                        time.sleep(1)
                    
                    # 检查是否有更多页面
                    has_more = page + 1 < result.get("total", 0)
                    page += 1
                    
                    self.logger.info("模式 %d 状态 %d 第 %d 页完成, 已爬取 %d 个谱面", 
                                   mode, status, page, success_count)
            
            if stop_requested or success_count >= max_charts:
                break
        
        self.logger.info("方式3完成: 成功 %d/%d 个谱面", success_count, max_charts)
        return success_count

    def crawl_all_sources_with_retry(self, max_charts_per_source=30, max_retries=3):
        """从所有数据源爬取谱面，带重试机制"""
        self.logger.info("开始多数据源爬取，每个源最大 %d 个谱面，最大重试次数 %d", 
                        max_charts_per_source, max_retries)
        
        total_success = 0
        sources = [
            ("主页爬取", self.crawl_from_homepage),
            ("最近变动", self.crawl_from_latest_page),
            ("API搜索", self.crawl_from_api_search)
        ]
        
        for source_name, crawl_func in sources:
            if stop_requested:
                self.logger.info("爬取被中断")
                break
                
            self.logger.info("=" * 60)
            self.logger.info("尝试数据源: %s", source_name)
            self.logger.info("=" * 60)
            
            retry_count = 0
            success_count = 0
            
            while retry_count <= max_retries:
                try:
                    if source_name == "主页爬取":
                        success_count = crawl_func(max_charts=max_charts_per_source)
                    elif source_name == "最近变动":
                        success_count = crawl_func(max_charts=max_charts_per_source)
                    else:  # API搜索
                        success_count = crawl_func(max_charts=max_charts_per_source)
                    
                    if success_count > 0:
                        self.logger.info("数据源 %s 成功爬取 %d 个谱面", source_name, success_count)
                        total_success += success_count
                        break
                    else:
                        self.logger.warning("数据源 %s 第 %d 次尝试未爬取到任何谱面", 
                                          source_name, retry_count + 1)
                        retry_count += 1
                        
                        if retry_count <= max_retries:
                            self.logger.info("等待 %d 秒后重试...", retry_count * 5)
                            time.sleep(retry_count * 5)
                
                except Exception as e:
                    self.logger.error("数据源 %s 第 %d 次尝试失败: %s", 
                                    source_name, retry_count + 1, e)
                    retry_count += 1
                    
                    if retry_count <= max_retries:
                        self.logger.info("等待 %d 秒后重试...", retry_count * 5)
                        time.sleep(retry_count * 5)
            
            if retry_count > max_retries:
                self.logger.warning("数据源 %s 重试 %d 次均失败，跳过", source_name, max_retries)
            
            # 源之间等待
            if not stop_requested:
                self.logger.info("等待5秒后切换到下一个数据源...")
                time.sleep(5)
        
        self.logger.info("所有数据源爬取完成: 总计 %d 个谱面", total_success)
        return total_success

    def crawl_cid_with_persistence(self, start_cid=1, end_cid=None, 
                                 requests_per_minute=10, max_errors=50, 
                                 progress_file="cid_progress.json", resume=True,
                                 retry_delay=30, process_retry_every=50):
        """
        持久的CID爬取，支持失败重试和进度恢复
        
        Args:
            start_cid: 起始CID
            end_cid: 结束CID
            requests_per_minute: 每分钟请求数
            max_errors: 连续错误最大次数
            progress_file: 进度文件路径
            resume: 是否从进度恢复
            retry_delay: 重试延迟秒数
            process_retry_every: 每N个请求处理一次重试队列
        """
        self.logger.info("=== 启动持久CID爬取 ===")
        self.logger.info("模式: %s, 起始: %d, 结束: %s, 速度: %d请求/分钟", 
                        "恢复" if resume else "从头开始", start_cid, 
                        "无限制" if end_cid is None else end_cid, requests_per_minute)
        
        # 加载或初始化进度
        if resume and os.path.exists(progress_file):
            progress = self._load_progress(progress_file)
            current_cid = progress.get('current_cid', start_cid)
            total_success = progress.get('total_success', 0)
            total_errors = progress.get('total_errors', 0)
            permanent_fails = set(progress.get('permanent_fails', []))
            
            # 加载重试队列
            retry_data = progress.get('retry_queue', [])
            self.retry_queue = deque(retry_data)
            
            self.logger.info("从进度文件恢复: CID=%d, 成功=%d, 错误=%d, 永久失败=%d, 重试队列=%d", 
                           current_cid, total_success, total_errors, len(permanent_fails), len(self.retry_queue))
        else:
            current_cid = start_cid
            total_success = 0
            total_errors = 0
            permanent_fails = set()
            self.retry_queue.clear()
            self.logger.info("从头开始爬取")
        
        # 计算请求间隔
        request_interval = 60.0 / requests_per_minute
        self.logger.info("请求间隔: %.1f秒, 重试延迟: %d秒", request_interval, retry_delay)
        
        consecutive_errors = 0
        request_count = 0
        
        try:
            while not stop_requested and (end_cid is None or current_cid <= end_cid):
                # 定期处理重试队列
                if request_count % process_retry_every == 0 and self.retry_queue:
                    self.logger.info("定期处理重试队列 (%d 个待重试)", len(self.retry_queue))
                    retry_success = self.process_retry_queue(retry_delay)
                    total_success += retry_success
                
                # 跳过已处理或永久失败的CID
                while (current_cid in self.processed_charts or 
                       current_cid in permanent_fails or
                       any(cid == current_cid for cid, _ in self.retry_queue)):
                    current_cid += 1
                    if end_cid is not None and current_cid > end_cid:
                        break
                
                if end_cid is not None and current_cid > end_cid:
                    break
                
                self.logger.info("处理 CID %d (进度: %d/%s)", 
                               current_cid, total_success, 
                               "未知" if end_cid is None else str(end_cid - start_cid + 1))
                
                # 爬取当前CID
                result = self.crawl_chart_detail_with_retry(current_cid)
                request_count += 1
                
                if result is True:  # 成功
                    total_success += 1
                    consecutive_errors = 0
                    self.logger.info("✓ CID %d 成功 (总计: %d)", current_cid, total_success)
                elif result is None:  # 明确不存在（404）
                    permanent_fails.add(current_cid)
                    consecutive_errors = 0
                    self.logger.debug("CID %d 不存在，标记为永久失败", current_cid)
                else:  # 失败但会重试
                    total_errors += 1
                    consecutive_errors += 1
                    self.logger.debug("CID %d 失败，已加入重试队列", current_cid)
                
                current_cid += 1
                
                # 错误过多时暂停
                if consecutive_errors >= max_errors:
                    self.logger.warning("连续错误达到 %d 次，暂停爬取并处理重试队列", max_errors)
                    retry_success = self.process_retry_queue(retry_delay * 2)  # 更长的重试间隔
                    total_success += retry_success
                    consecutive_errors = 0
                    
                    if self.retry_queue:
                        self.logger.info("重试队列仍有 %d 个项目，继续处理", len(self.retry_queue))
                    else:
                        self.logger.info("重试队列已清空，恢复正常爬取")
                
                # 保存进度（每10个请求或重试队列有变化时）
                if (request_count % 10 == 0 or 
                    len(self.retry_queue) > 0 and request_count % 5 == 0):
                    self._save_comprehensive_progress(
                        progress_file, current_cid, total_success, total_errors, 
                        permanent_fails, self.retry_queue
                    )
                    self.logger.debug("进度保存: CID=%d, 成功=%d, 错误=%d", 
                                    current_cid, total_success, total_errors)
                
                # 请求间隔（加入随机抖动）
                actual_delay = request_interval * (0.8 + 0.4 * random.random())
                time.sleep(actual_delay)
                
        except KeyboardInterrupt:
            self.logger.info("用户主动中断爬取")
        finally:
            # 最终保存进度
            self._save_comprehensive_progress(
                progress_file, current_cid, total_success, total_errors,
                permanent_fails, self.retry_queue
            )
            self.logger.info("最终进度保存: CID=%d, 成功=%d, 错误=%d, 重试队列=%d", 
                           current_cid, total_success, total_errors, len(self.retry_queue))
        
        # 最后处理剩余的重试队列
        if self.retry_queue and not stop_requested:
            self.logger.info("处理剩余的重试队列 (%d 个项目)", len(self.retry_queue))
            retry_success = self.process_retry_queue(retry_delay)
            total_success += retry_success
        
        self.logger.info("持久CID爬取完成: 成功 %d, 错误 %d", total_success, total_errors)
        return total_success

    def _load_progress(self, progress_file):
        """加载爬取进度"""
        try:
            with open(progress_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            self.logger.warning("加载进度文件失败: %s，使用默认值", e)
            return {}

    def _save_comprehensive_progress(self, progress_file, current_cid, success_count, 
                                   error_count, permanent_fails, retry_queue):
        """保存完整的爬取进度"""
        try:
            progress = {
                'current_cid': current_cid,
                'total_success': success_count,
                'total_errors': error_count,
                'permanent_fails': list(permanent_fails),
                'retry_queue': list(retry_queue),
                'last_save': datetime.now().isoformat(),
                'processed_charts_count': len(self.processed_charts),
                'processed_songs_count': len(self.processed_songs)
            }
            
            with open(progress_file, 'w', encoding='utf-8') as f:
                json.dump(progress, f, ensure_ascii=False, indent=2)
                
        except Exception as e:
            self.logger.error("保存进度文件失败: %s", e)

    def get_progress_status(self, progress_file="cid_progress.json"):
        """获取当前爬取状态"""
        if not os.path.exists(progress_file):
            return "无进度文件"
        
        try:
            progress = self._load_progress(progress_file)
            current_cid = progress.get('current_cid', 1)
            total_success = progress.get('total_success', 0)
            total_errors = progress.get('total_errors', 0)
            permanent_fails = len(progress.get('permanent_fails', []))
            retry_queue = len(progress.get('retry_queue', []))
            last_save = progress.get('last_save', '未知')
            
            status = (
                f"当前CID: {current_cid}\n"
                f"成功: {total_success}\n"
                f"错误: {total_errors}\n"
                f"永久失败: {permanent_fails}\n"
                f"待重试: {retry_queue}\n"
                f"最后保存: {last_save}"
            )
            return status
            
        except Exception as e:
            return f"读取进度文件失败: {e}"

    def crawl_by_sid_increment(self, start_sid=1, end_sid=None, 
                              requests_per_minute=10, max_errors=50,
                              progress_file="sid_progress.json", resume=True,
                              skip_empty_songs=True, max_cids_per_song=50):
        """
        按照SID递增爬取，然后获取每个SID下的所有CID
        
        Args:
            start_sid: 起始SID
            end_sid: 结束SID
            requests_per_minute: 每分钟请求数
            max_errors: 连续错误最大次数
            progress_file: 进度文件路径
            resume: 是否从进度恢复
            skip_empty_songs: 是否跳过没有谱面的歌曲
            max_cids_per_song: 每首歌曲最大CID数量限制
        """
        self.logger.info("=== 启动SID优先爬取策略 ===")
        self.logger.info("模式: %s, 起始SID: %d, 结束SID: %s, 速度: %d请求/分钟", 
                        "恢复" if resume else "从头开始", start_sid, 
                        "无限制" if end_sid is None else end_sid, requests_per_minute)
        
        # 加载或初始化进度
        if resume and os.path.exists(progress_file):
            progress = self._load_sid_progress(progress_file)
            current_sid = progress.get('current_sid', start_sid)
            total_songs = progress.get('total_songs', 0)
            total_charts = progress.get('total_charts', 0)
            total_errors = progress.get('total_errors', 0)
            empty_songs = set(progress.get('empty_songs', []))
            failed_songs = set(progress.get('failed_songs', []))
            
            self.logger.info("从进度文件恢复: SID=%d, 歌曲=%d, 谱面=%d, 错误=%d, 空歌曲=%d, 失败歌曲=%d", 
                           current_sid, total_songs, total_charts, total_errors, len(empty_songs), len(failed_songs))
        else:
            current_sid = start_sid
            total_songs = 0
            total_charts = 0
            total_errors = 0
            empty_songs = set()
            failed_songs = set()
            self.logger.info("从头开始爬取")
        
        # 计算请求间隔
        request_interval = 60.0 / requests_per_minute
        self.logger.info("请求间隔: %.1f秒", request_interval)
        
        consecutive_errors = 0
        request_count = 0
        
        try:
            while not stop_requested and (end_sid is None or current_sid <= end_sid):
                # 跳过已处理或已知为空的SID
                while (current_sid in empty_songs or 
                       current_sid in failed_songs or
                       current_sid in self.processed_songs):
                    current_sid += 1
                    if end_sid is not None and current_sid > end_sid:
                        break
                
                if end_sid is not None and current_sid > end_sid:
                    break
                
                self.logger.info("处理 SID %d (进度: 歌曲=%d, 谱面=%d)", 
                               current_sid, total_songs, total_charts)
                
                # 获取该SID下的所有CID
                cids = self.get_charts_from_song_page(current_sid)
                request_count += 1
                
                if cids:
                    self.logger.info("SID %d 有 %d 个谱面: %s", current_sid, len(cids), cids[:10])  # 只显示前10个
                    
                    # 限制每首歌曲的CID数量
                    if len(cids) > max_cids_per_song:
                        self.logger.warning("SID %d 有 %d 个谱面，超过限制 %d，只处理前 %d 个", 
                                          current_sid, len(cids), max_cids_per_song, max_cids_per_song)
                        cids = cids[:max_cids_per_song]
                    
                    # 爬取该SID下的所有CID
                    song_success_count = 0
                    for cid in cids:
                        if stop_requested:
                            break
                        
                        # 跳过已处理的CID
                        if cid in self.processed_charts:
                            continue
                        
                        self.logger.info("爬取 CID %d (SID %d 的第 %d/%d 个谱面)", 
                                       cid, current_sid, song_success_count + 1, len(cids))
                        
                        result = self.crawl_chart_detail_with_retry(cid)
                        request_count += 1
                        
                        if result is True:  # 成功
                            song_success_count += 1
                            total_charts += 1
                            consecutive_errors = 0
                            self.logger.info("✓ CID %d 成功 (SID %d: %d/%d)", 
                                           cid, current_sid, song_success_count, len(cids))
                        elif result is None:  # 明确不存在
                            self.logger.debug("CID %d 不存在", cid)
                        else:  # 失败
                            total_errors += 1
                            consecutive_errors += 1
                            self.logger.warning("CID %d 爬取失败", cid)
                        
                        # CID之间的延迟
                        time.sleep(request_interval)
                    
                    if song_success_count > 0:
                        total_songs += 1
                        self.logger.info("✓ SID %d 完成: %d/%d 个谱面成功", 
                                       current_sid, song_success_count, len(cids))
                    else:
                        self.logger.warning("SID %d 没有成功爬取任何谱面", current_sid)
                        failed_songs.add(current_sid)
                    
                else:
                    # 没有找到CID
                    if skip_empty_songs:
                        empty_songs.add(current_sid)
                        self.logger.debug("SID %d 没有谱面，标记为空", current_sid)
                    else:
                        self.logger.info("SID %d 没有找到谱面", current_sid)
                
                current_sid += 1
                consecutive_errors = 0  # 重置错误计数，因为每个SID都是独立的
                
                # 错误过多时暂停
                if consecutive_errors >= max_errors:
                    self.logger.warning("连续错误达到 %d 次，暂停爬取", max_errors)
                    self.logger.info("等待60秒后继续...")
                    time.sleep(60)
                    consecutive_errors = 0
                
                # 保存进度（每10个SID或每50个请求）
                if (request_count % 50 == 0 or 
                    (current_sid - start_sid) % 10 == 0):
                    self._save_sid_progress(
                        progress_file, current_sid, total_songs, total_charts, 
                        total_errors, empty_songs, failed_songs
                    )
                    self.logger.info("进度保存: SID=%d, 歌曲=%d, 谱面=%d, 错误=%d", 
                                   current_sid, total_songs, total_charts, total_errors)
                
                # SID之间的延迟（比CID之间更长）
                actual_delay = request_interval * (1.0 + 0.5 * random.random())
                time.sleep(actual_delay)
                    
        except KeyboardInterrupt:
            self.logger.info("用户主动中断爬取")
        finally:
            # 最终保存进度
            self._save_sid_progress(
                progress_file, current_sid, total_songs, total_charts,
                total_errors, empty_songs, failed_songs
            )
            self.logger.info("最终进度保存: SID=%d, 歌曲=%d, 谱面=%d, 错误=%d", 
                           current_sid, total_songs, total_charts, total_errors)
        
        self.logger.info("SID优先爬取完成: 歌曲 %d, 谱面 %d, 错误 %d", 
                       total_songs, total_charts, total_errors)
        return total_songs, total_charts

    def _load_sid_progress(self, progress_file):
        """加载SID爬取进度"""
        try:
            with open(progress_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            self.logger.warning("加载SID进度文件失败: %s，使用默认值", e)
            return {}

    def _save_sid_progress(self, progress_file, current_sid, total_songs, 
                          total_charts, total_errors, empty_songs, failed_songs):
        """保存SID爬取进度"""
        try:
            progress = {
                'current_sid': current_sid,
                'total_songs': total_songs,
                'total_charts': total_charts,
                'total_errors': total_errors,
                'empty_songs': list(empty_songs),
                'failed_songs': list(failed_songs),
                'last_save': datetime.now().isoformat(),
                'processed_charts_count': len(self.processed_charts),
                'processed_songs_count': len(self.processed_songs)
            }
            
            with open(progress_file, 'w', encoding='utf-8') as f:
                json.dump(progress, f, ensure_ascii=False, indent=2)
                
        except Exception as e:
            self.logger.error("保存SID进度文件失败: %s", e)

    def get_sid_progress_status(self, progress_file="sid_progress.json"):
        """获取SID爬取状态"""
        if not os.path.exists(progress_file):
            return "无SID进度文件"
        
        try:
            progress = self._load_sid_progress(progress_file)
            current_sid = progress.get('current_sid', 1)
            total_songs = progress.get('total_songs', 0)
            total_charts = progress.get('total_charts', 0)
            total_errors = progress.get('total_errors', 0)
            empty_songs = len(progress.get('empty_songs', []))
            failed_songs = len(progress.get('failed_songs', []))
            last_save = progress.get('last_save', '未知')
            
            status = (
                f"当前SID: {current_sid}\n"
                f"成功歌曲: {total_songs}\n"
                f"成功谱面: {total_charts}\n"
                f"错误: {total_errors}\n"
                f"空歌曲: {empty_songs}\n"
                f"失败歌曲: {failed_songs}\n"
                f"最后保存: {last_save}"
            )
            return status
            
        except Exception as e:
            return f"读取SID进度文件失败: {e}"

    def crawl_sid_backwards(self, start_sid=None, max_requests_per_minute=10, 
                           progress_file="sid_backwards_progress.json", resume=True):
        """
        向后爬取SID，直到遇到404自动停止
        
        Args:
            start_sid: 起始SID（如果为None则从进度文件恢复或从1开始）
            max_requests_per_minute: 每分钟最大请求数
            progress_file: 进度文件路径
            resume: 是否从进度恢复
        """
        self.logger.info("=== 启动向后SID爬取模式 ===")
        
        # 加载或初始化进度
        if resume and os.path.exists(progress_file):
            progress = self._load_sid_backwards_progress(progress_file)
            current_sid = progress.get('current_sid')
            last_valid_sid = progress.get('last_valid_sid')
            total_songs = progress.get('total_songs', 0)
            total_charts = progress.get('total_charts', 0)
            total_errors = progress.get('total_errors', 0)
            consecutive_404s = progress.get('consecutive_404s', 0)
            
            self.logger.info("从进度文件恢复: 当前SID=%s, 最后有效SID=%s, 歌曲=%d, 谱面=%d, 错误=%d, 连续404=%d", 
                           current_sid, last_valid_sid, total_songs, total_charts, total_errors, consecutive_404s)
            
            # 如果没有当前SID，使用最后有效SID或起始SID
            if current_sid is None:
                current_sid = last_valid_sid if last_valid_sid else start_sid
        else:
            current_sid = start_sid if start_sid else 1
            last_valid_sid = None
            total_songs = 0
            total_charts = 0
            total_errors = 0
            consecutive_404s = 0
            self.logger.info("从头开始爬取，起始SID: %s", current_sid)
        
        if current_sid is None:
            self.logger.error("无法确定起始SID，请指定start_sid参数")
            return total_songs, total_charts
        
        # 计算请求间隔
        request_interval = 60.0 / max_requests_per_minute
        self.logger.info("请求间隔: %.1f秒", request_interval)
        
        max_consecutive_404s = 10  # 连续遇到10个404就认为到达末尾
        
        try:
            while not stop_requested and consecutive_404s < max_consecutive_404s:
                self.logger.info("处理 SID %d (连续404: %d/%d)", 
                               current_sid, consecutive_404s, max_consecutive_404s)
                
                # 检查是否已处理过（避免重复）
                if current_sid in self.processed_songs:
                    self.logger.debug("SID %d 已处理过，跳过", current_sid)
                    current_sid += 1
                    continue
                
                # 获取该SID下的所有CID
                cids = self.get_charts_from_song_page(current_sid)
                
                if cids:
                    # 成功获取到CID，重置404计数
                    consecutive_404s = 0
                    last_valid_sid = current_sid
                    
                    self.logger.info("SID %d 有 %d 个谱面", current_sid, len(cids))
                    
                    # 爬取该SID下的所有CID
                    song_success_count = 0
                    for cid in cids:
                        if stop_requested:
                            break
                        
                        # 跳过已处理的CID
                        if cid in self.processed_charts:
                            continue
                        
                        self.logger.info("爬取 CID %d (SID %d 的第 %d/%d 个谱面)", 
                                       cid, current_sid, song_success_count + 1, len(cids))
                        
                        result = self.crawl_chart_detail_with_retry(cid)
                        
                        if result is True:  # 成功
                            song_success_count += 1
                            total_charts += 1
                            self.logger.info("✓ CID %d 成功 (SID %d: %d/%d)", 
                                           cid, current_sid, song_success_count, len(cids))
                        elif result is None:  # 明确不存在
                            self.logger.debug("CID %d 不存在", cid)
                        else:  # 失败
                            total_errors += 1
                            self.logger.warning("CID %d 爬取失败", cid)
                        
                        # CID之间的延迟
                        time.sleep(request_interval)
                    
                    if song_success_count > 0:
                        total_songs += 1
                        self.logger.info("✓ SID %d 完成: %d/%d 个谱面成功", 
                                       current_sid, song_success_count, len(cids))
                    else:
                        self.logger.info("SID %d 没有新谱面需要爬取", current_sid)
                    
                else:
                    # 没有找到CID，增加404计数
                    consecutive_404s += 1
                    self.logger.info("SID %d 返回空数据 (连续404: %d/%d)", 
                                   current_sid, consecutive_404s, max_consecutive_404s)
                    
                    # 如果是第一个404，记录为可能的最后一个有效SID
                    if consecutive_404s == 1 and last_valid_sid is None and current_sid > 1:
                        last_valid_sid = current_sid - 1
                        self.logger.info("第一个404，记录最后有效SID为: %d", last_valid_sid)
                
                # 移动到下一个SID
                current_sid += 1
                
                # 定期保存进度（每10个SID或每遇到404时）
                if (current_sid % 10 == 0 or consecutive_404s > 0 or 
                    stop_requested or consecutive_404s >= max_consecutive_404s):
                    self._save_sid_backwards_progress(
                        progress_file, current_sid, last_valid_sid, total_songs, 
                        total_charts, total_errors, consecutive_404s
                    )
                    self.logger.debug("进度保存: SID=%d, 最后有效=%s, 歌曲=%d, 谱面=%d, 错误=%d, 连续404=%d", 
                                    current_sid, last_valid_sid, total_songs, total_charts, total_errors, consecutive_404s)
                
                # SID之间的延迟
                actual_delay = request_interval * (1.0 + 0.5 * random.random())
                time.sleep(actual_delay)
                    
        except KeyboardInterrupt:
            self.logger.info("用户主动中断爬取")
        except Exception as e:
            self.logger.error("向后SID爬取出错: %s", e, exc_info=True)
        finally:
            # 最终保存进度
            self._save_sid_backwards_progress(
                progress_file, current_sid, last_valid_sid, total_songs,
                total_charts, total_errors, consecutive_404s
            )
            
            if consecutive_404s >= max_consecutive_404s:
                self.logger.info("已达到连续 %d 个404，自动停止爬取", max_consecutive_404s)
                if last_valid_sid:
                    self.logger.info("检测到的最后一个有效SID: %d", last_valid_sid)
            
            self.logger.info("向后SID爬取完成: 歌曲 %d, 谱面 %d, 错误 %d", 
                           total_songs, total_charts, total_errors)
        
        return total_songs, total_charts

    def _save_sid_backwards_progress(self, progress_file, current_sid, last_valid_sid, 
                                   total_songs, total_charts, total_errors, consecutive_404s):
        """保存向后SID爬取进度"""
        try:
            progress = {
                'current_sid': current_sid,
                'last_valid_sid': last_valid_sid,
                'total_songs': total_songs,
                'total_charts': total_charts,
                'total_errors': total_errors,
                'consecutive_404s': consecutive_404s,
                'last_save': datetime.now().isoformat(),
                'processed_charts_count': len(self.processed_charts),
                'processed_songs_count': len(self.processed_songs)
            }
            
            with open(progress_file, 'w', encoding='utf-8') as f:
                json.dump(progress, f, ensure_ascii=False, indent=2)
                
        except Exception as e:
            self.logger.error("保存向后SID进度文件失败: %s", e)

    def _load_sid_backwards_progress(self, progress_file):
        """加载向后SID爬取进度"""
        try:
            with open(progress_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            self.logger.warning("加载向后SID进度文件失败: %s，使用默认值", e)
            return {}

    def get_sid_backwards_progress_status(self, progress_file="sid_backwards_progress.json"):
        """获取向后SID爬取状态"""
        if not os.path.exists(progress_file):
            return "无向后SID进度文件"
        
        try:
            progress = self._load_sid_backwards_progress(progress_file)
            current_sid = progress.get('current_sid', '未知')
            last_valid_sid = progress.get('last_valid_sid', '未知')
            total_songs = progress.get('total_songs', 0)
            total_charts = progress.get('total_charts', 0)
            total_errors = progress.get('total_errors', 0)
            consecutive_404s = progress.get('consecutive_404s', 0)
            last_save = progress.get('last_save', '未知')
            
            status = (
                f"当前SID: {current_sid}\n"
                f"最后有效SID: {last_valid_sid}\n"
                f"成功歌曲: {total_songs}\n"
                f"成功谱面: {total_charts}\n"
                f"错误: {total_errors}\n"
                f"连续404: {consecutive_404s}\n"
                f"最后保存: {last_save}"
            )
            return status
            
        except Exception as e:
            return f"读取向后SID进度文件失败: {e}"

    def retry_failed_items(self, progress_files=None, requests_per_minute=5, 
                          max_retries=3, remove_successful=True):
        """
        重新爬取所有失败的项目（从进度文件中）
        
        Args:
            progress_files: 进度文件列表，如果为None则使用默认文件
            requests_per_minute: 每分钟请求数
            max_retries: 最大重试次数
            remove_successful: 是否从失败列表中移除成功的项目
        """
        if progress_files is None:
            progress_files = [
                "cid_progress.json",
                "sid_progress.json", 
                "sid_backwards_progress.json"
            ]
        
        self.logger.info("=== 开始重新爬取失败项目 ===")
        self.logger.info("进度文件: %s", progress_files)
        
        all_failed_items = set()
        progress_data = {}
        
        # 从所有进度文件中收集失败项目
        for progress_file in progress_files:
            if not os.path.exists(progress_file):
                self.logger.info("进度文件不存在: %s", progress_file)
                continue
                
            try:
                with open(progress_file, 'r', encoding='utf-8') as f:
                    progress = json.load(f)
                    progress_data[progress_file] = progress
                    
                    # 从CID进度文件收集失败项目
                    if 'permanent_fails' in progress:
                        for cid in progress['permanent_fails']:
                            all_failed_items.add(('cid', cid))
                    
                    if 'retry_queue' in progress:
                        for item in progress['retry_queue']:
                            if isinstance(item, list) and len(item) > 0:
                                all_failed_items.add(('cid', item[0]))
                    
                    # 从SID进度文件收集失败项目
                    if 'empty_songs' in progress:
                        for sid in progress['empty_songs']:
                            all_failed_items.add(('sid', sid))
                    
                    if 'failed_songs' in progress:
                        for sid in progress['failed_songs']:
                            all_failed_items.add(('sid', sid))
                            
            except Exception as e:
                self.logger.error("读取进度文件 %s 失败: %s", progress_file, e)
        
        if not all_failed_items:
            self.logger.info("没有找到失败项目")
            return 0, 0
        
        self.logger.info("找到 %d 个失败项目需要重新爬取", len(all_failed_items))
        
        # 计算请求间隔
        request_interval = 60.0 / requests_per_minute
        success_count = 0
        total_count = len(all_failed_items)
        
        # 重新爬取所有失败项目
        for i, (item_type, item_id) in enumerate(all_failed_items):
            if stop_requested:
                break
                
            self.logger.info("重新爬取 %s %d (%d/%d)", 
                           item_type.upper(), item_id, i+1, total_count)
            
            result = False
            if item_type == 'cid':
                result = self.crawl_chart_detail_with_retry(item_id)
            elif item_type == 'sid':
                cids = self.get_charts_from_song_page(item_id)
                if cids:
                    for cid in cids:
                        if self.crawl_chart_detail_with_retry(cid):
                            result = True
                            break
            
            if result:
                success_count += 1
                self.logger.info("✓ 重新爬取 %s %d 成功", item_type.upper(), item_id)
                
                # 从失败列表中移除成功的项目
                if remove_successful:
                    self._remove_from_failed_lists(progress_data, item_type, item_id)
            else:
                self.logger.warning("✗ 重新爬取 %s %d 失败", item_type.upper(), item_id)
            
            # 请求间隔
            time.sleep(request_interval)
        
        # 保存更新后的进度文件
        if remove_successful:
            for progress_file, progress in progress_data.items():
                try:
                    with open(progress_file, 'w', encoding='utf-8') as f:
                        json.dump(progress, f, ensure_ascii=False, indent=2)
                    self.logger.info("已更新进度文件: %s", progress_file)
                except Exception as e:
                    self.logger.error("保存进度文件 %s 失败: %s", progress_file, e)
        
        self.logger.info("失败项目重新爬取完成: 成功 %d/%d", success_count, total_count)
        return success_count, total_count

    def _remove_from_failed_lists(self, progress_data, item_type, item_id):
        """从失败列表中移除项目"""
        for progress_file, progress in progress_data.items():
            updated = False
            
            if item_type == 'cid':
                # 从permanent_fails中移除
                if 'permanent_fails' in progress and item_id in progress['permanent_fails']:
                    progress['permanent_fails'].remove(item_id)
                    updated = True
                
                # 从retry_queue中移除
                if 'retry_queue' in progress:
                    new_retry_queue = [item for item in progress['retry_queue'] 
                                     if not (isinstance(item, list) and len(item) > 0 and item[0] == item_id)]
                    if len(new_retry_queue) != len(progress['retry_queue']):
                        progress['retry_queue'] = new_retry_queue
                        updated = True
            
            elif item_type == 'sid':
                # 从empty_songs中移除
                if 'empty_songs' in progress and item_id in progress['empty_songs']:
                    progress['empty_songs'].remove(item_id)
                    updated = True
                
                # 从failed_songs中移除
                if 'failed_songs' in progress and item_id in progress['failed_songs']:
                    progress['failed_songs'].remove(item_id)
                    updated = True
            
            if updated:
                progress['last_save'] = datetime.now().isoformat()
                self.logger.debug("从 %s 中移除 %s %d", progress_file, item_type, item_id)

    def test_api(self):
        """测试API访问"""
        try:
            result = self.search_charts(mode=0, status=2, page=0)
            if result and "list" in result:
                self.logger.info("API测试成功 - 获取到 %d 个谱面", len(result["list"]))
                return True
            else:
                self.logger.warning("API测试失败 - 无有效数据返回")
                return False
        except Exception as e:
            self.logger.error("API测试失败: %s", e)
            return False

def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='STB谱面爬虫')
    parser.add_argument('--days', type=int, default=7, help='爬取最近多少天的数据（默认7天）')
    parser.add_argument('--modes', type=str, help='指定模式，逗号分隔（如0,1,2）')
    parser.add_argument('--statuses', type=str, help='指定状态，逗号分隔（0=Alpha,1=Beta,2=Stable）')
    parser.add_argument('--cid', type=str, help='爬取指定谱面ID，逗号分隔')
    parser.add_argument('--sid', type=str, help='爬取指定歌曲ID的所有谱面，逗号分隔')
    parser.add_argument('--once', action='store_true', help='运行一次后退出')
    parser.add_argument('--test', action='store_true', help='只测试连接')
    parser.add_argument('--test-api', action='store_true', help='测试API访问')
    parser.add_argument('--no-api', action='store_true', help='不使用API搜索，使用其他数据源')
    parser.add_argument('--source', choices=['all', 'home', 'latest', 'api'], default='all',
                       help='选择数据源: all=全部, home=主页, latest=最近变动, api=API搜索')
    parser.add_argument('--max-charts', type=int, default=256, help='每个数据源最大爬取数量（默认256）')
    parser.add_argument('--max-retries', type=int, default=3, help='每个数据源最大重试次数（默认3）')
    parser.add_argument('--skip-test', action='store_true', help='跳过连接测试')
    parser.add_argument('--log-level', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'], 
                       default='INFO', help='日志级别（默认INFO）')
    parser.add_argument('--log-file', help='指定日志文件路径')
    
    # 新增的CID爬取参数
    parser.add_argument('--cid-crawl', action='store_true', help='启动CID爬取模式')
    parser.add_argument('--start-cid', type=int, default=1, help='起始CID（默认1）')
    parser.add_argument('--end-cid', type=int, help='结束CID（默认无限制）')
    parser.add_argument('--rpm', type=int, default=8, help='每分钟请求数（默认8）')
    parser.add_argument('--no-resume', action='store_true', help='不从进度恢复，从头开始')
    parser.add_argument('--progress-file', default='cid_progress.json', help='进度文件路径')
    parser.add_argument('--status', action='store_true', help='显示当前爬取状态')
    
    # 新增的SID爬取参数
    parser.add_argument('--sid-crawl', action='store_true', help='启动SID优先爬取')
    parser.add_argument('--start-sid', type=int, default=1, help='起始SID（默认1）')
    parser.add_argument('--end-sid', type=int, help='结束SID（默认无限制）')
    parser.add_argument('--max-cids-per-song', type=int, default=999, help='每首歌曲最大CID数量（默认999）')
    parser.add_argument('--no-skip-empty', action='store_true', help='不跳过空歌曲')
    parser.add_argument('--sid-progress-file', default='sid_progress.json', help='SID进度文件路径')
    parser.add_argument('--sid-status', action='store_true', help='显示SID爬取状态')
    
    # 新增的向后SID爬取参数
    parser.add_argument('--sid-backwards', action='store_true', help='启动向后SID爬取模式')
    parser.add_argument('--start-sid-backwards', type=int, help='向后爬取的起始SID（默认从进度恢复或从1开始）')
    parser.add_argument('--sid-backwards-rpm', type=int, default=10, help='向后SID爬取每分钟请求数（默认10）')
    parser.add_argument('--sid-backwards-progress-file', default='sid_backwards_progress.json', 
                       help='向后SID进度文件路径')
    parser.add_argument('--sid-backwards-status', action='store_true', help='显示向后SID爬取状态')
    
    # 新增的重试失败项目参数
    parser.add_argument('--retry-failed', action='store_true', help='重新爬取所有失败的项目')
    parser.add_argument('--retry-rpm', type=int, default=5, help='重试时的每分钟请求数（默认5）')
    parser.add_argument('--retry-max-retries', type=int, default=3, help='重试时的最大重试次数（默认3）')
    parser.add_argument('--no-remove-successful', action='store_true', 
                       help='重试成功后不从失败列表中移除')
    parser.add_argument('--progress-files', type=str, 
                       help='指定要处理的进度文件，逗号分隔（默认：cid_progress.json,sid_progress.json,sid_backwards_progress.json）')
    
    args = parser.parse_args()
    
    # 设置详细日志
    log_level = getattr(logging, args.log_level)
    setup_detailed_logging(log_level=log_level, log_file=args.log_file)
    
    logger = logging.getLogger(__name__)
    logger.info("STB爬虫启动，参数: %s", vars(args))
    
    # 显示状态
    if args.status:
        crawler = STBCrawler()
        status = crawler.get_progress_status(args.progress_file)
        print("当前爬取状态:")
        print(status)
        return
    
    if args.sid_status:
        crawler = STBCrawler()
        status = crawler.get_sid_progress_status(args.sid_progress_file)
        print("SID爬取状态:")
        print(status)
        return
    
    if args.sid_backwards_status:
        crawler = STBCrawler()
        status = crawler.get_sid_backwards_progress_status(args.sid_backwards_progress_file)
        print("向后SID爬取状态:")
        print(status)
        return
    
    # 初始化数据库
    init_database()
    
    # 创建爬虫实例
    crawler = STBCrawler()
    
    # 测试连接（除非跳过）
    if not args.skip_test:
        logger.info("开始连接测试...")
        if not crawler.test_connection():
            logger.error("连接测试失败，请检查网络或认证信息")
            logger.info("可以使用 --skip-test 跳过连接测试")
            return
        logger.info("连接测试成功")
    else:
        logger.info("跳过连接测试")
    
    if args.test:
        logger.info("连接测试成功，退出")
        return
    
    if args.test_api:
        if crawler.test_api():
            logger.info("API测试成功")
        else:
            logger.error("API测试失败")
        return
    
    # 重试失败项目模式
    if args.retry_failed:
        logger.info("启动重试失败项目模式")
        progress_files = None
        if args.progress_files:
            progress_files = [f.strip() for f in args.progress_files.split(',')]
        
        success, total = crawler.retry_failed_items(
            progress_files=progress_files,
            requests_per_minute=args.retry_rpm,
            max_retries=args.retry_max_retries,
            remove_successful=not args.no_remove_successful
        )
        logger.info("重试失败项目完成: 成功 %d/%d", success, total)
        return
    
    # 向后SID爬取模式
    if args.sid_backwards:
        logger.info("启动向后SID爬取模式")
        songs, charts = crawler.crawl_sid_backwards(
            start_sid=args.start_sid_backwards,
            max_requests_per_minute=args.sid_backwards_rpm,
            progress_file=args.sid_backwards_progress_file,
            resume=not args.no_resume
        )
        logger.info("向后SID爬取完成: %d 首歌曲, %d 个谱面", songs, charts)
        return
    
    # SID优先爬取模式
    if args.sid_crawl:
        logger.info("启动SID优先爬取模式")
        songs, charts = crawler.crawl_by_sid_increment(
            start_sid=args.start_sid,
            end_sid=args.end_sid,
            requests_per_minute=args.rpm,
            progress_file=args.sid_progress_file,
            resume=not args.no_resume,
            skip_empty_songs=not args.no_skip_empty,
            max_cids_per_song=args.max_cids_per_song
        )
        logger.info("SID爬取完成: %d 首歌曲, %d 个谱面", songs, charts)
        return
    
    # CID爬取模式
    if args.cid_crawl:
        logger.info("启动CID爬取模式")
        success = crawler.crawl_cid_with_persistence(
            start_cid=args.start_cid,
            end_cid=args.end_cid,
            requests_per_minute=args.rpm,
            progress_file=args.progress_file,
            resume=not args.no_resume
        )
        logger.info("CID爬取完成: 成功 %d 个谱面", success)
        return
    
    if args.cid:
        # 爬取指定谱面
        cid_list = [int(cid.strip()) for cid in args.cid.split(',')]
        success_count = 0
        for cid in cid_list:
            if crawler.crawl_chart_detail_with_retry(cid):
                success_count += 1
        logger.info("指定谱面爬取完成: 成功 %d/%d", success_count, len(cid_list))
    
    elif args.sid:
        # 爬取指定歌曲的所有谱面
        sid_list = [int(sid.strip()) for sid in args.sid.split(',')]
        success_count = 0
        for sid in sid_list:
            song_cids = crawler.get_charts_from_song_page(sid)
            if song_cids:
                for cid in song_cids:
                    if crawler.crawl_chart_detail_with_retry(cid):
                        success_count += 1
        logger.info("指定歌曲爬取完成: 成功 %d 个谱面", success_count)
    
    else:
        # 默认行为：依次尝试三种方式，带重试机制
        if args.source == 'all':
            # 使用所有数据源，带重试
            crawler.crawl_all_sources_with_retry(
                max_charts_per_source=args.max_charts,
                max_retries=args.max_retries
            )
        elif args.source == 'home':
            crawler.crawl_from_homepage(max_charts=args.max_charts)
        elif args.source == 'latest':
            crawler.crawl_from_latest_page(max_charts=args.max_charts)
        elif args.source == 'api':
            modes = None
            if args.modes:
                modes = [int(mode.strip()) for mode in args.modes.split(',')]
            
            statuses = None  
            if args.statuses:
                statuses = [int(status.strip()) for status in args.statuses.split(',')]
            
            crawler.crawl_from_api_search(modes=modes, statuses=statuses, max_charts=args.max_charts)
    
    # 更新爬取状态
    crawler.update_crawl_state()
    logger.info("爬虫运行完成")

if __name__ == "__main__":
    main()
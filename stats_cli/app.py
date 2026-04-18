# malody_stats.py
import sqlite3
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import cmd
import os
import sys
from typing import Dict, List, Tuple, Optional
import matplotlib.dates as mdates
from matplotlib.ticker import MaxNLocator, LogLocator, FuncFormatter
import subprocess
import atexit
import signal
from functools import wraps
import shutil
import re
import math
import json
import copy                     # 新增导入，用于深拷贝选择器
from selector import global_selector, MCSelector
from utils.stats_export_runner import parse_export_request, run_export
from utils.stats_update_runner import build_update_command, run_streaming_command, split_cli_args
from stats_cli.plugins.registry import install_plugins

# 修复matplotlib中文字体问题
def setup_chinese_font():
    """设置中文字体支持（增强版）"""
    import matplotlib.pyplot as plt
    import matplotlib.font_manager as fm
    import platform
    import os

    # 常见中文字体名称（按优先级排序）
    chinese_font_names = [
        'Microsoft YaHei',        # Windows
        'SimHei',                  # Windows
        'PingFang SC',             # macOS
        'STHeiti',                 # macOS
        'WenQuanYi Micro Hei',     # Linux
        'Noto Sans CJK SC',        # Linux
        'Droid Sans Fallback',     # Android
    ]

    # 如果系统是 Windows，可以指定完整路径（备选）
    if platform.system() == 'Windows':
        # 尝试从系统字体目录加载
        win_font_dir = os.path.join(os.environ.get('WINDIR', 'C:\\Windows'), 'Fonts')
        win_fonts = {
            'Microsoft YaHei': os.path.join(win_font_dir, 'msyh.ttc'),
            'SimHei': os.path.join(win_font_dir, 'simhei.ttf'),
        }
        for name, path in win_fonts.items():
            if os.path.exists(path):
                fm.fontManager.addfont(path)
                chinese_font_names.insert(0, name)  # 优先使用已找到的字体

    # 查找系统中可用的中文字体
    available_fonts = set(f.name for f in fm.fontManager.ttflist)
    found_font = None
    for font_name in chinese_font_names:
        if font_name in available_fonts:
            found_font = font_name
            break

    if found_font:
        plt.rcParams['font.sans-serif'] = [found_font] + plt.rcParams['font.sans-serif']
        plt.rcParams['axes.unicode_minus'] = False
        print(f"已设置中文字体: {found_font}")
        return True
    else:
        print("警告: 未找到支持中文的字体，图表中的中文可能显示为方块")
        print("可尝试手动安装以下字体之一: " + ", ".join(chinese_font_names))
        return False

# 在程序初始化时调用字体设置
setup_chinese_font()


# PowerShell 颜色支持修复
def enable_powershell_colors():
    """在 PowerShell 中启用 ANSI 颜色支持"""
    if sys.platform == "win32":
        try:
            # 方法1: 通过设置环境变量启用虚拟终端
            os.environ["TERM"] = "xterm-256color"
            
            # 方法2: 使用 ctypes 启用虚拟终端处理
            if hasattr(sys, 'getwindowsversion'):
                import ctypes
                from ctypes import wintypes
                
                kernel32 = ctypes.windll.kernel32
                STD_OUTPUT_HANDLE = -11
                
                # 获取标准输出句柄
                hstdout = kernel32.GetStdHandle(STD_OUTPUT_HANDLE)
                
                # 获取当前控制台模式
                mode = wintypes.DWORD()
                if kernel32.GetConsoleMode(hstdout, ctypes.byref(mode)):
                    # 启用虚拟终端处理
                    ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
                    new_mode = mode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING
                    kernel32.SetConsoleMode(hstdout, new_mode)
                    return True
        except:
            pass
    return False

# 在程序启动时启用 PowerShell 颜色
enable_powershell_colors()

# 修复Python 3.12中SQLite datetime适配器的弃用警告
def adapt_datetime(dt):
    return dt.isoformat()

def convert_datetime(s):
    return datetime.fromisoformat(s.decode())

sqlite3.register_adapter(datetime, adapt_datetime)
sqlite3.register_converter("timestamp", convert_datetime)

# 设置matplotlib使用Agg后端（无GUI）
plt.switch_backend('Agg')

# 设置图表字体颜色为深色，避免与背景冲突
plt.rcParams['text.color'] = 'black'
plt.rcParams['axes.labelcolor'] = 'black'
plt.rcParams['xtick.color'] = 'black'
plt.rcParams['ytick.color'] = 'black'
plt.rcParams['axes.titlecolor'] = 'black'

# 颜色定义 (ANSI转义码)
class Colors:
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    MAGENTA = '\033[95m'
    CYAN = '\033[96m'
    WHITE = '\033[97m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'
    END = '\033[0m'

def color_enabled():
    """检查当前环境是否支持颜色输出"""
    if sys.platform == "win32":
        # 在 Windows 上检查是否在支持颜色的终端中运行
        try:
            # 检查是否在 Windows Terminal、PowerShell 5.1+ 或支持 ANSI 的 CMD 中运行
            term_program = os.environ.get('TERM_PROGRAM', '')
            term = os.environ.get('TERM', '')
            
            # Windows Terminal 或现代 PowerShell
            if 'WindowsTerminal' in term_program or 'TERM' in os.environ:
                return True
            
            # 检查 PowerShell 版本（5.1+ 支持 ANSI）
            import subprocess
            result = subprocess.run(['powershell', '$PSVersionTable.PSVersion.Major'], 
                                  capture_output=True, text=True, timeout=2)
            if result.returncode == 0 and result.stdout.strip().isdigit():
                ps_version = int(result.stdout.strip())
                if ps_version >= 5:
                    return True
                    
            # 最后的手段：尝试检测控制台能力
            import ctypes
            from ctypes import wintypes
            
            kernel32 = ctypes.windll.kernel32
            STD_OUTPUT_HANDLE = -11
            hstdout = kernel32.GetStdHandle(STD_OUTPUT_HANDLE)
            
            mode = wintypes.DWORD()
            if kernel32.GetConsoleMode(hstdout, ctypes.byref(mode)):
                ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
                return (mode.value & ENABLE_VIRTUAL_TERMINAL_PROCESSING) != 0
                
        except:
            pass
        return False
    else:
        # 非 Windows 系统通常支持颜色
        return True

def colorize(text, color):
    """有条件地添加颜色到文本"""
    if color_enabled():
        return f"{color}{text}{Colors.END}"
    return text

def db_safe_operation(func):
    """装饰器用于确保数据库操作安全"""
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        try:
            return func(self, *args, **kwargs)
        except sqlite3.Error as e:
            print(colorize(f"数据库错误: {e}", Colors.RED))
            return False
        except Exception as e:
            print(colorize(f"操作错误: {e}", Colors.RED))
            return False
    return wrapper

def format_change(change_value, reverse=False, is_percent=False):
    """格式化变化值，添加颜色"""
    if change_value is None:
        return "N/A"
    
    if change_value == 0:
        return "0"
    
    if is_percent:
        change_str = f"{change_value:+.2f}%"
    else:
        change_str = f"{change_value:+d}"
    
    # 对于排名变化，负数表示进步（排名上升）
    if reverse:
        if change_value < 0:
            return colorize(change_str, Colors.GREEN)  # 进步
        elif change_value > 0:
            return colorize(change_str, Colors.RED)    # 退步
    else:
        if change_value > 0:
            return colorize(change_str, Colors.GREEN)  # 增加
        elif change_value < 0:
            return colorize(change_str, Colors.RED)    # 减少
    
    return change_str

def format_number(number):
    """格式化大数字，添加千位分隔符"""
    if number is None:
        return "N/A"
    return f"{number:,}"

def get_terminal_width():
    """获取终端宽度"""
    try:
        return shutil.get_terminal_size().columns
    except:
        return 80

def get_separator(width=None):
    """获取自适应分隔线"""
    if width is None:
        width = get_terminal_width()
    return colorize("=" * min(width, 120), Colors.CYAN)

def get_subseparator(width=None):
    """获取自适应子分隔线"""
    if width is None:
        width = get_terminal_width()
    return colorize("-" * min(width, 100), Colors.CYAN)

class MalodyViz(cmd.Cmd):
    """Malody排行榜数据可视化工具"""
    
    intro = colorize("\n欢迎使用Malody排行榜数据可视化工具!\n\n", Colors.CYAN) + \
            "输入 " + colorize("help", Colors.GREEN) + " 或 " + colorize("?", Colors.GREEN) + " 查看命令列表。\n" + \
            "输入 " + colorize("help <命令名>", Colors.GREEN) + " 查看具体命令的详细说明。\n\n" + \
            "所有生成的图表将保存在 " + colorize("viz_output", Colors.YELLOW) + " 目录中。\n" + \
            "提示: 可以使用 " + colorize("ls", Colors.GREEN) + " 命令查看当前目录文件。\n"
    prompt = colorize("(malody-viz) ", Colors.BLUE)
    
    def __init__(self):
        super().__init__()
        self.db_path = "malody_rankings.db"
        self.conn = None
        self.current_mode = -1  # -1 表示所有模式
        self.output_dir = "viz_output"
        
        atexit.register(self.cleanup)
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
        
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)
        
        self.connect_db()
        
        # 初始化选择器
        self.selector = global_selector
        self.selector.current_mode = self.current_mode
        
        self.mode_names = {
            -1: "All",  # 所有模式
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
        
        # 自动修复数据库问题
        self.auto_repair_database()
    
    def connect_db(self):
        """连接到SQLite数据库"""
        try:
            self.conn = sqlite3.connect(
                self.db_path, 
                detect_types=sqlite3.PARSE_DECLTYPES,
                check_same_thread=False
            )
            self.conn.execute("PRAGMA foreign_keys = ON")
            self.conn.execute("PRAGMA busy_timeout = 3000")
            print(colorize(f"成功连接到数据库: {self.db_path}", Colors.GREEN))
        except sqlite3.Error as e:
            print(colorize(f"数据库连接错误: {e}", Colors.RED))
            sys.exit(1)
    
    def cleanup(self):
        """清理资源"""
        if self.conn:
            try:
                self.conn.close()
                print(colorize("\n数据库连接已安全关闭", Colors.GREEN))
            except:
                pass
    
    def signal_handler(self, signum, frame):
        """处理中断信号"""
        print(colorize("\n正在安全退出...", Colors.YELLOW))
        self.cleanup()
        sys.exit(0)
    
    def emptyline(self):
        """空行时不执行任何操作"""
        pass
    
    def get_unique_filename(self, base_name, extension):
        """生成不重复的文件名，添加时间戳"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        name_only = os.path.splitext(base_name)[0]
        return f"{name_only}_{timestamp}.{extension}"
    
    @db_safe_operation
    def auto_repair_database(self):
        """
        自动修复数据库常见问题
        """
        cursor = self.conn.cursor()
        
        print(colorize("\n正在检查数据库状态...", Colors.CYAN))
        
        try:
            # 检查数据库完整性
            cursor.execute("PRAGMA integrity_check")
            integrity_result = cursor.fetchone()[0]
            
            issues_found = []
            
            if integrity_result != "ok":
                issues_found.append(f"数据库完整性: {integrity_result}")
                print(colorize(f"发现数据库完整性问题: {integrity_result}", Colors.YELLOW))
            
            # 检查状态为1的记录是否存在但统计不显示的问题
            cursor.execute("SELECT COUNT(*) FROM charts WHERE status = 1")
            beta_count = cursor.fetchone()[0]
            
            cursor.execute("SELECT cid FROM charts WHERE status = 1 LIMIT 1")
            beta_exists = cursor.fetchone()
            
            if beta_count == 0 and beta_exists:
                issues_found.append("状态为1的记录存在但统计不显示")
                print(colorize("发现状态统计不一致问题", Colors.YELLOW))
            
            # 如果有问题，自动修复
            if issues_found:
                print(colorize(f"发现 {len(issues_found)} 个问题，正在自动修复...", Colors.YELLOW))
                
                # 修复索引
                print("修复数据库索引...")
                cursor.execute("REINDEX")
                
                # 清理数据库
                print("清理数据库...")
                cursor.execute("VACUUM")
                
                # 修复已知的状态不一致问题
                print("修复状态不一致问题...")
                known_issues = [
                    (139970, 1),  # CID 139970 应该是状态1
                    # 可以在这里添加其他已知的问题CID和正确状态
                ]
                
                for cid, correct_status in known_issues:
                    cursor.execute("SELECT status FROM charts WHERE cid = ?", (cid,))
                    current_status = cursor.fetchone()
                    if current_status and current_status[0] != correct_status:
                        cursor.execute("UPDATE charts SET status = ? WHERE cid = ?", (correct_status, cid))
                        print(f"  修复 CID {cid}: 状态 {current_status[0]} -> {correct_status}")
                
                self.conn.commit()
                
                # 验证修复结果
                cursor.execute("PRAGMA integrity_check")
                new_integrity = cursor.fetchone()[0]
                
                if new_integrity == "ok":
                    print(colorize("自动修复完成！数据库现在正常。", Colors.GREEN))
                else:
                    print(colorize(f"修复后完整性检查: {new_integrity}", Colors.YELLOW))
                    
            else:
                print(colorize("数据库状态正常，无需修复。", Colors.GREEN))
                
        except Exception as e:
            print(colorize(f"自动修复过程中发生错误: {e}", Colors.RED))

    @db_safe_operation
    def do_stb_pie(self, arg):
        """
        生成谱面分布饼状图（支持选择器筛选）
        
        用法: stb_pie [模式] [类型]
        参数:
        模式 - 可选，模式编号，默认为当前模式
        类型 - 可选，status(状态分布), level(难度分布), 默认为status
        
        示例:
        stb_pie        # 当前模式状态分布饼图
        stb_pie 0 level # 模式0难度分布饼图
        """
        args = arg.split()
        mode = self.current_mode
        chart_type = "status"
        
        if args:
            try:
                if args[0].isdigit():
                    mode = int(args[0])
                    if len(args) > 1:
                        chart_type = args[1].lower()
                else:
                    chart_type = args[0].lower()
                    if len(args) > 1 and args[1].isdigit():
                        mode = int(args[1])
            except ValueError:
                print(colorize("错误: 模式必须是数字", Colors.RED))
                return
        
        cursor = self.conn.cursor()
        
        if chart_type == "status":
            self._generate_status_pie(cursor, mode)
        elif chart_type == "level":
            self._generate_level_pie(cursor, mode)
        else:
            print(colorize(f"错误: 不支持的图表类型 '{chart_type}'", Colors.RED))

    def _generate_status_pie(self, cursor, mode):
        """生成状态分布饼图"""
        # 使用选择器构建谱面查询条件
        where_clause, params = self.selector.build_chart_sql_where("c")
        
        # 如果选择器中没有指定模式，使用当前模式
        if not self.selector.filters['modes'] and self.selector.current_mode != -1:
            where_clause += " AND c.mode = ?" if where_clause != "1=1" else "c.mode = ?"
            params.append(mode)
        
        cursor.execute(
            f"SELECT c.status, COUNT(*) FROM charts c WHERE {where_clause} GROUP BY c.status",
            params
        )
        status_data = cursor.fetchall()
        
        if not status_data:
            print(colorize(f"没有找到符合条件的谱面数据", Colors.YELLOW))
            return
        
        status_names = {0: "Alpha", 1: "Beta", 2: "Stable"}
        labels = []
        sizes = []
        
        for status, count in status_data:
            labels.append(status_names.get(status, f"未知({status})"))
            sizes.append(count)
        
        # 生成饼图
        fig, ax = plt.subplots(figsize=(10, 8))
        colors = plt.cm.Set3(np.linspace(0, 1, len(labels)))
        wedges, texts, autotexts = ax.pie(sizes, labels=labels, autopct='%1.1f%%', 
                                        colors=colors, startangle=90)
        
        # 美化文本
        for autotext in autotexts:
            autotext.set_color('white')
            autotext.set_fontweight('bold')
        
        mode_name = self.mode_names.get(mode, "未知")
        ax.set_title(f'谱面状态分布 - 模式 {mode} ({mode_name})\n筛选条件: {self.selector.get_current_selection()}', 
                    fontsize=14, fontweight='bold')
        
        # 保存图表
        base_filename = f"stb_status_pie_mode{mode}.png"
        filename = self.get_unique_filename(base_filename, "png")
        filepath = os.path.join(self.output_dir, filename)
        plt.tight_layout()
        plt.savefig(filepath, dpi=150, facecolor='white')
        plt.close()
        
        print(colorize(f"\n已生成状态分布饼图: {filepath}", Colors.GREEN))

    def _generate_level_pie(self, cursor, mode):
        """生成难度分布饼图"""
        # 使用选择器构建谱面查询条件
        where_clause, params = self.selector.build_chart_sql_where("c")
        
        # 如果选择器中没有指定模式，使用当前模式
        if not self.selector.filters['modes'] and self.selector.current_mode != -1:
            where_clause += " AND c.mode = ?" if where_clause != "1=1" else "c.mode = ?"
            params.append(mode)
        
        # 过滤无效的难度值
        where_clause += " AND c.level IS NOT NULL AND c.level != '' AND CAST(c.level AS REAL) > 0"
        
        cursor.execute(
            f"SELECT c.level, COUNT(*) FROM charts c WHERE {where_clause} GROUP BY c.level ORDER BY CAST(c.level AS REAL)",
            params
        )
        level_data = cursor.fetchall()
        
        if not level_data:
            print(colorize(f"没有找到符合条件的难度数据", Colors.YELLOW))
            return
        
        # 分组处理：将难度分组以避免饼图过于碎片化
        level_groups = {}
        for level, count in level_data:
            try:
                level_float = float(level)
                if level_float < 5:
                    group = "1-4"
                elif level_float < 10:
                    group = "5-9" 
                elif level_float < 15:
                    group = "10-14"
                else:
                    group = "15+"
                
                level_groups[group] = level_groups.get(group, 0) + count
            except ValueError:
                continue
        
        if not level_groups:
            print(colorize("没有有效的难度数据", Colors.YELLOW))
            return
        
        labels = list(level_groups.keys())
        sizes = list(level_groups.values())
        
        # 生成饼图
        fig, ax = plt.subplots(figsize=(10, 8))
        colors = plt.cm.viridis(np.linspace(0, 1, len(labels)))
        wedges, texts, autotexts = ax.pie(sizes, labels=labels, autopct='%1.1f%%', 
                                        colors=colors, startangle=90)
        
        for autotext in autotexts:
            autotext.set_color('white')
            autotext.set_fontweight('bold')
        
        mode_name = self.mode_names.get(mode, "未知")
        ax.set_title(f'谱面难度分布 - 模式 {mode} ({mode_name})\n筛选条件: {self.selector.get_current_selection()}', 
                    fontsize=14, fontweight='bold')
        
        # 保存图表
        base_filename = f"stb_level_pie_mode{mode}.png"
        filename = self.get_unique_filename(base_filename, "png")
        filepath = os.path.join(self.output_dir, filename)
        plt.tight_layout()
        plt.savefig(filepath, dpi=150, facecolor='white')
        plt.close()
        
        print(colorize(f"\n已生成难度分布饼图: {filepath}", Colors.GREEN))
        
    @db_safe_operation
    def do_stb_recent(self, arg):
        """
        查询最近更新的谱面（支持选择器筛选）
        
        用法: stb_recent [天数] [模式] [数量]
        参数:
        天数 - 可选，最近多少天内更新的谱面，默认为7天
        模式 - 可选，模式编号，默认为当前模式  
        数量 - 可选，要显示的谱面数量，默认为10
        
        示例:
        stb_recent        # 最近7天更新的谱面
        stb_recent 30 0 20 # 模式0最近30天前20个更新谱面
        """
        args = arg.split()
        days = 7
        mode = self.current_mode
        limit = 10
        
        if args:
            try:
                days = int(args[0])
                if len(args) > 1:
                    mode = int(args[1])
                    if len(args) > 2:
                        limit = int(args[2])
            except ValueError:
                print(colorize("错误: 参数必须是数字", Colors.RED))
                return
        
        cursor = self.conn.cursor()
        
        # 使用选择器构建谱面查询条件
        where_clause, params = self.selector.build_chart_sql_where("c")
        
        # 如果选择器中没有时间筛选，使用参数中的天数
        if not self.selector.filters['time_range']:
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days)
            where_clause += " AND c.last_updated >= ?" if where_clause != "1=1" else "c.last_updated >= ?"
            params.append(start_date)
        
        # 如果选择器中没有指定模式，且当前模式不是所有模式，使用当前模式
        if not self.selector.filters['modes'] and self.selector.current_mode != -1:
            where_clause += " AND c.mode = ?" if where_clause != "1=1" else "c.mode = ?"
            params.append(mode)
        
        query = f"""
        SELECT c.cid, c.version, c.level, c.status, s.title, s.artist,
            c.creator_name, c.stabled_by_name, c.heat, c.donate_count, c.play_count, c.last_updated, c.crawl_time
        FROM charts c
        JOIN songs s ON c.sid = s.sid
        WHERE {where_clause}
        ORDER BY c.last_updated DESC
        LIMIT ?
        """
        params.append(limit)
        
        cursor.execute(query, params)
        results = cursor.fetchall()
        
        if not results:
            print(colorize(f"\n没有找到符合条件的谱面", Colors.YELLOW))
            return
        
        # 显示模式信息
        if self.selector.filters['modes']:
            mode_str = ", ".join([f"{m}({self.mode_names.get(m, '未知')})" for m in self.selector.filters['modes']])
        elif self.selector.current_mode != -1:
            mode_str = f"{self.selector.current_mode}({self.mode_names.get(self.selector.current_mode, '未知')})"
        else:
            mode_str = "所有模式"
        
        print(colorize(f"\n最近更新的谱面", Colors.CYAN))
        print(colorize(f"模式: {mode_str}", Colors.YELLOW))
        print(colorize(f"筛选条件: {self.selector.get_current_selection()}", Colors.YELLOW))
        print(get_separator())
        
        for cid, version, level, status, title, artist, creator, stabled, heat, donate, play, last_updated, crawl_time in results:
            status_name = {0: "Alpha", 1: "Beta", 2: "Stable"}.get(status, "Unknown")
            days_ago = (datetime.now() - last_updated).days if last_updated else "未知"
            
            print(f"{colorize(title, Colors.BOLD)} - {artist}")
            print(f"  版本: {version}, 难度: Lv.{level}, 状态: {status_name}")
            print(f"  创作者: {creator}, 稳定者: {stabled if stabled else 'N/A'}")
            print(f"  热度: {heat}, 打赏: {donate}, 游玩: {play}")
            print(f"  最后更新: {last_updated} ({days_ago}天前), CID: {cid}")
            print()
    
    @db_safe_operation  
    def do_stb_hot(self, arg):
        """
        显示热门谱面排行榜（支持选择器筛选）
        
        用法: stb_hot [模式] [排序字段] [数量]
        排序字段: heat(热度), donate_count(打赏数), play_count(游玩次数)
        
        示例:
        stb_hot           # 当前模式按热度前10
        stb_hot 0         # 模式0按热度前10  
        stb_hot 0 donate_count 5   # 模式0按打赏数前5
        """
        args = arg.split()
        mode = self.current_mode
        sort_field = "heat"
        limit = 10
        
        if args:
            try:
                if args[0].isdigit():
                    mode = int(args[0])
                    if len(args) > 1:
                        sort_field = args[1].lower()
                        if len(args) > 2:
                            limit = int(args[2])
                else:
                    sort_field = args[0].lower()
                    if len(args) > 1 and args[1].isdigit():
                        mode = int(args[1])
                        if len(args) > 2:
                            limit = int(args[2])
            except ValueError:
                print(colorize("错误: 参数必须是数字", Colors.RED))
                return
        
        valid_fields = ["heat", "donate_count", "play_count"]
        if sort_field not in valid_fields:
            print(colorize(f"错误: 排序字段必须是 {valid_fields} 之一", Colors.RED))
            return
        
        cursor = self.conn.cursor()
        
        # 使用选择器构建谱面查询条件
        where_clause, params = self.selector.build_chart_sql_where("c")
        
        # 如果选择器中没有指定模式，且当前模式不是所有模式，使用当前模式
        if not self.selector.filters['modes'] and self.selector.current_mode != -1:
            where_clause += " AND c.mode = ?" if where_clause != "1=1" else "c.mode = ?"
            params.append(mode)
        
        query = f"""
        SELECT c.cid, c.version, c.level, c.status, s.title, s.artist,
            c.creator_name, c.stabled_by_name, c.heat, c.donate_count, c.play_count, c.last_updated
        FROM charts c
        JOIN songs s ON c.sid = s.sid
        WHERE {where_clause}
        ORDER BY c.{sort_field} DESC
        LIMIT ?
        """
        params.append(limit)
        
        cursor.execute(query, params)
        results = cursor.fetchall()
        
        if not results:
            print(colorize(f"\n没有找到符合条件的谱面", Colors.YELLOW))
            return
        
        # 显示模式信息
        if self.selector.filters['modes']:
            mode_str = ", ".join([f"{m}({self.mode_names.get(m, '未知')})" for m in self.selector.filters['modes']])
        elif self.selector.current_mode != -1:
            mode_str = f"{self.selector.current_mode}({self.mode_names.get(self.selector.current_mode, '未知')})"
        else:
            mode_str = "所有模式"
        
        field_name = {"heat":"热度", "donate_count":"打赏数", "play_count":"游玩次数"}.get(sort_field, sort_field)
        print(colorize(f"\n热门谱面排行榜 ({field_name})", Colors.CYAN))
        print(colorize(f"模式: {mode_str}", Colors.YELLOW))
        print(colorize(f"筛选条件: {self.selector.get_current_selection()}", Colors.YELLOW))
        print(get_separator())
        
        for i, (cid, version, level, status, title, artist, creator, stabled, heat, donate, play, updated) in enumerate(results, 1):
            status_name = {0: "Alpha", 1: "Beta", 2: "Stable"}.get(status, "Unknown")
            value = heat if sort_field=="heat" else donate if sort_field=="donate_count" else play
            
            print(f"{colorize(f'#{i}', Colors.YELLOW)} {colorize(title, Colors.BOLD)} - {artist}")
            print(f"  难度: Lv.{level}, 状态: {status_name}, 版本: {version}")
            print(f"  创作者: {creator}, 稳定者: {stabled if stabled else 'N/A'}, {field_name}: {value}")
            print(f"  热度: {heat}, 打赏: {donate}, 游玩: {play}, CID: {cid}")
            print()
    
    @db_safe_operation
    def do_stb_summary(self, arg):
        """
        生成谱面综合统计报告（支持选择器筛选）
        
        用法: stb_summary [模式] [详细级别]
        参数:
        模式 - 可选，模式编号，默认为当前模式
        详细级别 - 可选，basic(基础), detailed(详细), 默认为basic
        
        示例:
        stb_summary           # 当前模式基础统计
        stb_summary 0 detailed # 模式0详细统计
        """
        args = arg.split()
        mode = self.current_mode
        detail_level = "basic"
        
        if args:
            try:
                if args[0].isdigit():
                    mode = int(args[0])
                    if len(args) > 1:
                        detail_level = args[1].lower()
                else:
                    detail_level = args[0].lower()
                    if len(args) > 1 and args[1].isdigit():
                        mode = int(args[1])
            except ValueError:
                print(colorize("错误: 模式必须是数字", Colors.RED))
                return
        
        cursor = self.conn.cursor()
        
        # 获取综合统计
        stats = self._get_comprehensive_stats(cursor, mode, detail_level)
        self._display_summary_report(stats, mode, detail_level)
        
        # 询问是否生成图表
        if detail_level == "detailed":
            chart_choice = input(colorize("\n是否生成统计图表? (y/N): ", Colors.CYAN)).lower()
            if chart_choice == 'y':
                self._generate_summary_charts(stats, mode)

    def _get_comprehensive_stats(self, cursor, mode, detail_level):
        """获取综合统计数据"""
        stats = {}
        
        # 使用选择器构建谱面查询条件
        where_clause, params = self.selector.build_chart_sql_where("c")
        
        # 如果选择器中没有指定模式，使用当前模式
        if not self.selector.filters['modes'] and self.selector.current_mode != -1:
            where_clause += " AND c.mode = ?" if where_clause != "1=1" else "c.mode = ?"
            params.append(mode)
        
        # 基础统计
        cursor.execute(f"SELECT COUNT(*) FROM charts c WHERE {where_clause}", params)
        stats['total_charts'] = cursor.fetchone()[0]
        
        cursor.execute(f"SELECT COUNT(DISTINCT c.sid) FROM charts c WHERE {where_clause}", params)
        stats['unique_songs'] = cursor.fetchone()[0]
        
        cursor.execute(f"SELECT COUNT(DISTINCT c.creator_name) FROM charts c WHERE {where_clause} AND c.creator_name IS NOT NULL", params)
        stats['unique_creators'] = cursor.fetchone()[0]
        
        # 时间统计
        cursor.execute(f"SELECT MIN(c.last_updated), MAX(c.last_updated) FROM charts c WHERE {where_clause} AND c.last_updated IS NOT NULL", params)
        min_max_dates = cursor.fetchone()
        stats['first_update'] = min_max_dates[0]
        stats['last_update'] = min_max_dates[1]
        
        # 热度统计
        cursor.execute(
            f"SELECT AVG(c.heat), MAX(c.heat), MIN(c.heat) FROM charts c WHERE {where_clause} AND c.heat > 0",
            params
        )
        heat_stats = cursor.fetchone()
        stats['heat_stats'] = {
            'avg': heat_stats[0] or 0,
            'max': heat_stats[1] or 0,
            'min': heat_stats[2] or 0
        }
        
        # 难度统计
        cursor.execute(
            f"SELECT AVG(CAST(c.level AS REAL)), MAX(CAST(c.level AS REAL)), MIN(CAST(c.level AS REAL)) FROM charts c WHERE {where_clause} AND c.level IS NOT NULL AND c.level != '' AND CAST(c.level AS REAL) > 0",
            params
        )
        level_stats = cursor.fetchone()
        stats['level_stats'] = {
            'avg': level_stats[0] or 0,
            'max': level_stats[1] or 0,
            'min': level_stats[2] or 0
        }
        
        # 状态分布
        cursor.execute(
            f"SELECT c.status, COUNT(*) FROM charts c WHERE {where_clause} GROUP BY c.status",
            params
        )
        stats['status_dist'] = dict(cursor.fetchall())
        
        if detail_level == "detailed":
            # 详细统计
            cursor.execute(
                f"SELECT c.creator_name, COUNT(*) as count FROM charts c WHERE {where_clause} AND c.creator_name IS NOT NULL GROUP BY c.creator_name ORDER BY count DESC LIMIT 20",
                params
            )
            stats['top_creators'] = cursor.fetchall()
            
            cursor.execute(
                f"SELECT c.level, COUNT(*) as count FROM charts c WHERE {where_clause} AND c.level IS NOT NULL AND c.level != '' AND CAST(c.level AS REAL) > 0 GROUP BY c.level ORDER BY CAST(c.level AS REAL)",
                params
            )
            stats['level_breakdown'] = cursor.fetchall()
            
            # 热度分布
            cursor.execute(
                f"SELECT COUNT(*) FROM charts c WHERE {where_clause} AND c.heat = 0",
                params
            )
            stats['zero_heat'] = cursor.fetchone()[0]
            
            cursor.execute(
                f"SELECT COUNT(*) FROM charts c WHERE {where_clause} AND c.heat BETWEEN 1 AND 10",
                params
            )
            stats['low_heat'] = cursor.fetchone()[0]
            
            cursor.execute(
                f"SELECT COUNT(*) FROM charts c WHERE {where_clause} AND c.heat BETWEEN 11 AND 50",
                params
            )
            stats['medium_heat'] = cursor.fetchone()[0]
            
            cursor.execute(
                f"SELECT COUNT(*) FROM charts c WHERE {where_clause} AND c.heat > 50",
                params
            )
            stats['high_heat'] = cursor.fetchone()[0]
            
            # 更新频率统计
            cursor.execute(
                f"SELECT strftime('%Y-%m', c.last_updated) as month, COUNT(*) FROM charts c WHERE {where_clause} AND c.last_updated IS NOT NULL GROUP BY month ORDER BY month DESC LIMIT 12",
                params
            )
            stats['monthly_updates'] = cursor.fetchall()
        
        return stats

    def _display_summary_report(self, stats, mode, detail_level):
        """显示综合统计报告"""
        mode_name = self.mode_names.get(mode, "未知")
        
        print(colorize(f"\n谱面综合统计报告", Colors.CYAN))
        print(colorize(f"筛选条件: {self.selector.get_current_selection()}", Colors.YELLOW))
        print(get_separator())
        
        # 基础概览
        print(colorize("\n📊 基础概览", Colors.BOLD))
        print(f"  总谱面数: {colorize(stats['total_charts'], Colors.GREEN)}")
        print(f"  唯一歌曲数: {stats['unique_songs']}")
        print(f"  创作者数: {stats['unique_creators']}")
        
        if stats['first_update'] and stats['last_update']:
            first_date = stats['first_update'].strftime('%Y-%m-%d') if hasattr(stats['first_update'], 'strftime') else stats['first_update']
            last_date = stats['last_update'].strftime('%Y-%m-%d') if hasattr(stats['last_update'], 'strftime') else stats['last_update']
            print(f"  数据时间范围: {first_date} 至 {last_date}")
        
        # 热度统计
        print(colorize("\n🔥 热度统计", Colors.BOLD))
        heat = stats['heat_stats']
        print(f"  平均热度: {heat['avg']:.1f}")
        print(f"  最高热度: {heat['max']}")
        print(f"  最低热度: {heat['min']}")
        # if heat['std'] > 0:
        #     print(f"  热度标准差: {heat['std']:.1f}")
        
        # 难度统计
        if stats['level_stats']['avg'] > 0:
            print(colorize("\n🎯 难度统计", Colors.BOLD))
            level = stats['level_stats']
            print(f"  平均难度: Lv.{level['avg']:.1f}")
            print(f"  最高难度: Lv.{level['max']}")
            print(f"  最低难度: Lv.{level['min']}")
        
        # 状态分布
        print(colorize("\n📝 状态分布", Colors.BOLD))
        status_names = {0: "Alpha", 1: "Beta", 2: "Stable"}
        for status, count in stats['status_dist'].items():
            status_name = status_names.get(status, f"未知({status})")
            percentage = (count / stats['total_charts']) * 100
            print(f"  {status_name}: {count} ({percentage:.1f}%)")
        
        if detail_level == "detailed":
            # 详细统计
            print(colorize("\n👑 顶级创作者 (前20)", Colors.BOLD))
            for i, (creator, count) in enumerate(stats['top_creators'][:10], 1):
                percentage = (count / stats['total_charts']) * 100
                print(f"  {i:2d}. {creator}: {count} 谱面 ({percentage:.1f}%)")
            
            # 热度分布
            print(colorize("\n📈 热度分布", Colors.BOLD))
            total_with_heat = stats['total_charts'] - stats['zero_heat']
            if total_with_heat > 0:
                print(f"  无热度: {stats['zero_heat']} ({stats['zero_heat']/stats['total_charts']*100:.1f}%)")
                print(f"  低热度 (1-10): {stats['low_heat']} ({stats['low_heat']/total_with_heat*100:.1f}%)")
                print(f"  中热度 (11-50): {stats['medium_heat']} ({stats['medium_heat']/total_with_heat*100:.1f}%)")
                print(f"  高热度 (50+): {stats['high_heat']} ({stats['high_heat']/total_with_heat*100:.1f}%)")
            
            # 月度更新
            if stats['monthly_updates']:
                print(colorize("\n📅 月度更新趋势 (最近12个月)", Colors.BOLD))
                for month, count in stats['monthly_updates']:
                    print(f"  {month}: {count} 个谱面")
    
    def _generate_summary_charts(self, stats, mode):
        """生成综合统计图表"""
        mode_name = self.mode_names.get(mode, "未知")
        
        # 创建多个子图
        fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(16, 12))
        fig.suptitle(f'谱面综合统计 - 模式 {mode} ({mode_name})', fontsize=16, fontweight='bold')
        
        # 1. 状态分布饼图
        status_names = {0: "Alpha", 1: "Beta", 2: "Stable"}
        status_labels = [status_names.get(s, f"未知({s})") for s in stats['status_dist'].keys()]
        status_sizes = list(stats['status_dist'].values())
        
        colors1 = ['#ff9999', '#66b3ff', '#99ff99']
        ax1.pie(status_sizes, labels=status_labels, autopct='%1.1f%%', colors=colors1, startangle=90)
        ax1.set_title('状态分布')
        
        # 2. 热度分布柱状图
        heat_categories = ['无热度', '低热度', '中热度', '高热度']
        heat_values = [stats['zero_heat'], stats['low_heat'], stats['medium_heat'], stats['high_heat']]
        colors2 = ['#cccccc', '#ffeb3b', '#ff9800', '#f44336']
        
        bars = ax2.bar(heat_categories, heat_values, color=colors2)
        ax2.set_title('热度分布')
        ax2.set_ylabel('谱面数量')
        
        # 添加数值标签
        for bar, value in zip(bars, heat_values):
            height = bar.get_height()
            ax2.text(bar.get_x() + bar.get_width()/2., height + 0.1,
                    f'{value}', ha='center', va='bottom')
        
        # 3. 难度分布柱状图（如果数据存在）
        if hasattr(stats, 'level_breakdown') and stats['level_breakdown']:
            levels = [str(item[0]) for item in stats['level_breakdown']]
            counts = [item[1] for item in stats['level_breakdown']]
            
            ax3.bar(levels, counts, color='skyblue')
            ax3.set_title('难度分布')
            ax3.set_ylabel('谱面数量')
            ax3.tick_params(axis='x', rotation=45)
        else:
            ax3.text(0.5, 0.5, '无难度数据', ha='center', va='center', transform=ax3.transAxes)
            ax3.set_title('难度分布')
        
        # 4. 创作者排行榜（前10）
        if hasattr(stats, 'top_creators') and stats['top_creators']:
            creators = [item[0][:15] + '...' if len(item[0]) > 15 else item[0] for item in stats['top_creators'][:10]]
            creator_counts = [item[1] for item in stats['top_creators'][:10]]
            
            y_pos = range(len(creators))
            ax4.barh(y_pos, creator_counts, color='lightgreen')
            ax4.set_yticks(y_pos)
            ax4.set_yticklabels(creators)
            ax4.set_title('创作者排行榜 (前10)')
            ax4.set_xlabel('谱面数量')
        else:
            ax4.text(0.5, 0.5, '无创作者数据', ha='center', va='center', transform=ax4.transAxes)
            ax4.set_title('创作者排行榜')
        
        plt.tight_layout()
        
        # 保存图表
        base_filename = f"stb_summary_mode{mode}.png"
        filename = self.get_unique_filename(base_filename, "png")
        filepath = os.path.join(self.output_dir, filename)
        plt.savefig(filepath, dpi=150, facecolor='white', bbox_inches='tight')
        plt.close()
        
        print(colorize(f"\n已生成综合统计图表: {filepath}", Colors.GREEN))
    
    @db_safe_operation
    def do_stb_quality(self, arg):
        """
        检查数据质量（支持选择器筛选）
        
        用法: stb_quality [模式]
        参数:
        模式 - 可选，模式编号，默认为当前模式
        
        示例:
        stb_quality      # 当前模式数据质量检查
        stb_quality 0    # 模式0数据质量检查
        """
        args = arg.split()
        mode = self.current_mode
        if args:
            try:
                mode = int(args[0])
            except ValueError:
                print(colorize("错误: 模式必须是数字", Colors.RED))
                return
        
        cursor = self.conn.cursor()
        
        # 使用选择器构建谱面查询条件
        where_clause, params = self.selector.build_chart_sql_where("c")
        
        # 如果选择器中没有指定模式，使用当前模式
        if not self.selector.filters['modes'] and self.selector.current_mode != -1:
            where_clause += " AND c.mode = ?" if where_clause != "1=1" else "c.mode = ?"
            params.append(mode)
        
        print(colorize(f"\n数据质量检查", Colors.CYAN))
        print(colorize(f"筛选条件: {self.selector.get_current_selection()}", Colors.YELLOW))
        print(get_separator())
        
        # 检查数据完整性
        issues = []
        
        # 1. 检查缺失字段
        cursor.execute(f"SELECT COUNT(*) FROM charts c WHERE {where_clause} AND c.creator_name IS NULL", params)
        missing_creator = cursor.fetchone()[0]
        if missing_creator > 0:
            issues.append(f"缺失创作者: {missing_creator} 个谱面")
        
        cursor.execute(f"SELECT COUNT(*) FROM charts c WHERE {where_clause} AND c.level IS NULL", params)
        missing_level = cursor.fetchone()[0]
        if missing_level > 0:
            issues.append(f"缺失难度: {missing_level} 个谱面")
        
        cursor.execute(f"SELECT COUNT(*) FROM charts c WHERE {where_clause} AND c.last_updated IS NULL", params)
        missing_update = cursor.fetchone()[0]
        if missing_update > 0:
            issues.append(f"缺失更新时间: {missing_update} 个谱面")
        
        # 2. 检查数据一致性
        cursor.execute(f"SELECT COUNT(*) FROM charts c LEFT JOIN songs s ON c.sid = s.sid WHERE {where_clause} AND s.sid IS NULL", params)
        orphan_charts = cursor.fetchone()[0]
        if orphan_charts > 0:
            issues.append(f"孤立的谱面记录: {orphan_charts} 个")
        
        # 3. 检查异常值
        cursor.execute(f"SELECT COUNT(*) FROM charts c WHERE {where_clause} AND c.heat < 0", params)
        negative_heat = cursor.fetchone()[0]
        if negative_heat > 0:
            issues.append(f"负热度值: {negative_heat} 个谱面")
        
        cursor.execute(f"SELECT COUNT(*) FROM charts c WHERE {where_clause} AND c.donate_count < 0", params)
        negative_donate = cursor.fetchone()[0]
        if negative_donate > 0:
            issues.append(f"负打赏数: {negative_donate} 个谱面")
        
        # 显示结果
        if issues:
            print(colorize("❌ 发现数据质量问题:", Colors.RED))
            for issue in issues:
                print(f"  • {issue}")
        else:
            print(colorize("✅ 数据质量良好，未发现问题", Colors.GREEN))
        
        # 显示数据完整性统计
        cursor.execute(f"SELECT COUNT(*) FROM charts c WHERE {where_clause}", params)
        total_charts = cursor.fetchone()[0]
        
        completeness_stats = []
        if total_charts > 0:
            completeness_stats.append(f"总谱面数: {total_charts}")
            
            creator_completeness = ((total_charts - missing_creator) / total_charts) * 100
            completeness_stats.append(f"创作者完整性: {creator_completeness:.1f}%")
            
            level_completeness = ((total_charts - missing_level) / total_charts) * 100
            completeness_stats.append(f"难度完整性: {level_completeness:.1f}%")
            
            update_completeness = ((total_charts - missing_update) / total_charts) * 100
            completeness_stats.append(f"更新时间完整性: {update_completeness:.1f}%")
        
        print(colorize("\n📊 数据完整性统计:", Colors.BOLD))
        for stat in completeness_stats:
            print(f"  {stat}")
            
    @db_safe_operation
    def do_stb_trends(self, arg):
        """
        分析谱面数据趋势（支持选择器筛选）
        
        用法: stb_trends [模式] [时间段] [--by 分组维度]
        时间段: days(日), months(月), 默认为months
        分组维度: mode(按模式), creator(按创作者), status(按状态)
        
        示例:
        stb_trends           # 当前模式月度趋势
        stb_trends 0 days    # 模式0每日趋势
        stb_trends 0 months --by creator   # 按创作者分组月度趋势
        """
        args = arg.split()
        mode = self.current_mode
        period = "months"
        group_by = None
        
        i = 0
        while i < len(args):
            if args[i] in ["days", "months"]:
                period = args[i]
                i += 1
            elif args[i] == "--by" and i+1 < len(args):
                group_by = args[i+1].lower()
                i += 2
            elif args[i].isdigit():
                mode = int(args[i])
                i += 1
            else:
                i += 1
        
        cursor = self.conn.cursor()
        
        try:
            # 使用选择器构建基础查询条件（排除时间筛选）
            base_filters = self.selector.filters.copy()
            base_filters['time_range'] = None
            temp_selector = MCSelector()
            temp_selector.set_filters(**base_filters)
            
            where_clause, params = temp_selector.build_chart_sql_where("c")
            
            # 如果选择器中没有指定模式，使用当前模式
            if not temp_selector.filters['modes'] and temp_selector.current_mode != -1:
                if where_clause != "1=1":
                    where_clause += " AND c.mode = ?"
                else:
                    where_clause = "c.mode = ?"
                params.append(mode)
            
            # 添加时间范围条件
            if period == "days":
                time_condition = "c.last_updated >= date('now', '-30 days')"
                group_by_time = "DATE(c.last_updated)"
                order_by = "DATE(c.last_updated)"
                period_name = "每日"
                x_label = "日期"
            else:
                time_condition = "c.last_updated >= date('now', '-1 year')"
                group_by_time = "strftime('%Y-%m', c.last_updated)"
                order_by = "strftime('%Y-%m', c.last_updated)"
                period_name = "月度"
                x_label = "月份"
            
            if where_clause != "1=1":
                where_clause += f" AND {time_condition}"
            else:
                where_clause = time_condition
            
            # 构建分组查询
            if group_by == "mode":
                group_col = f"{group_by_time}, c.mode"
                select_cols = f"{group_by_time} as period, c.mode, COUNT(*) as count"
                title_suffix = "按模式分组"
            elif group_by == "creator":
                group_col = f"{group_by_time}, c.creator_name"
                select_cols = f"{group_by_time} as period, c.creator_name, COUNT(*) as count"
                title_suffix = "按创作者分组"
            elif group_by == "status":
                group_col = f"{group_by_time}, c.status"
                select_cols = f"{group_by_time} as period, c.status, COUNT(*) as count"
                title_suffix = "按状态分组"
            else:
                group_col = group_by_time
                select_cols = f"{group_by_time} as period, COUNT(*) as count"
                title_suffix = ""
            
            query = f"""
            SELECT {select_cols}
            FROM charts c
            WHERE {where_clause}
            GROUP BY {group_col}
            ORDER BY {order_by}
            """
            
            cursor.execute(query, params)
            trend_data = cursor.fetchall()
            
            if not trend_data:
                print(colorize(f"没有找到趋势数据", Colors.YELLOW))
                return
            
            mode_name = self.mode_names.get(mode, "未知")
            print(colorize(f"\n谱面{period_name}趋势 {title_suffix}", Colors.CYAN))
            print(colorize(f"筛选条件: {self.selector.get_current_selection()}", Colors.YELLOW))
            print(get_separator())
            
            if group_by is None:
                # 简单趋势
                dates = [row[0] for row in trend_data]
                counts = [row[1] for row in trend_data]
                total_updates = sum(counts)
                avg_updates = total_updates / len(counts) if counts else 0
                max_updates = max(counts) if counts else 0
                min_updates = min(counts) if counts else 0
                
                print(f"总更新谱面: {total_updates}")
                print(f"平均{period_name}更新: {avg_updates:.1f}")
                print(f"最高{period_name}更新: {max_updates}")
                print(f"最低{period_name}更新: {min_updates}")
                
                print(colorize(f"\n{period_name}详细数据:", Colors.BOLD))
                for date, count in trend_data[-10:]:
                    print(f"  {date}: {count} 个谱面")
                
                # 生成图表
                fig, ax = plt.subplots(figsize=(12, 6))
                ax.plot(dates, counts, 'o-', linewidth=2, markersize=6, color='#2196F3')
                ax.fill_between(dates, counts, alpha=0.3, color='#2196F3')
                ax.axhline(y=avg_updates, color='red', linestyle='--', alpha=0.7, label=f'平均值: {avg_updates:.1f}')
                ax.set_title(f'谱面{period_name}更新趋势\n筛选条件: {self.selector.get_current_selection()}')
                ax.set_xlabel(x_label)
                ax.set_ylabel('更新谱面数量')
                ax.legend()
                ax.grid(True, alpha=0.3)
                plt.xticks(rotation=45)
                plt.tight_layout()
                
                base_filename = f"stb_trends_{period}_mode{mode}.png"
                filename = self.get_unique_filename(base_filename, "png")
                filepath = os.path.join(self.output_dir, filename)
                plt.savefig(filepath, dpi=150, facecolor='white')
                plt.close()
                print(colorize(f"\n已生成趋势图表: {filepath}", Colors.GREEN))
            
            else:
                # 分组趋势：简单打印表格
                print(colorize(f"\n分组趋势数据 (前20行):", Colors.BOLD))
                for row in trend_data[:20]:
                    if group_by == "mode":
                        period, m, cnt = row
                        mode_name_g = self.mode_names.get(m, "未知")
                        print(f"  {period} 模式 {m}({mode_name_g}): {cnt}")
                    elif group_by == "creator":
                        period, creator, cnt = row
                        print(f"  {period} {creator}: {cnt}")
                    elif group_by == "status":
                        period, status, cnt = row
                        status_name = {0:"Alpha",1:"Beta",2:"Stable"}.get(status, "未知")
                        print(f"  {period} {status_name}: {cnt}")
                
                # 可以选择生成堆叠柱状图，这里省略
                print(colorize("\n详细图表生成暂不支持分组趋势", Colors.YELLOW))
            
        except sqlite3.Error as e:
            print(colorize(f"数据库错误: {e}", Colors.RED))
        except Exception as e:
            print(colorize(f"操作错误: {e}", Colors.RED))
    
    @db_safe_operation
    def do_stb_compare(self, arg):
        """
        比较不同模式的谱面数据（支持选择器筛选）
        
        用法: stb_compare [模式列表]
        参数:
        模式列表 - 可选，要比较的模式编号，用逗号分隔，默认为所有模式
        
        示例:
        stb_compare           # 比较所有模式
        stb_compare 0,3,5     # 比较模式0,3,5
        """
        if arg:
            try:
                modes = [int(m.strip()) for m in arg.split(',')]
                # 验证模式有效性
                for mode in modes:
                    if mode not in self.mode_names or mode == -1:
                        print(colorize(f"错误: 模式 {mode} 不存在", Colors.RED))
                        return
            except ValueError:
                print(colorize("错误: 模式必须是数字", Colors.RED))
                return
        else:
            modes = list(self.mode_names.keys())
            modes.remove(-1)  # 移除"所有模式"选项
        
        cursor = self.conn.cursor()
        
        print(colorize(f"\n模式比较分析", Colors.CYAN))
        print(colorize(f"筛选条件: {self.selector.get_current_selection()}", Colors.YELLOW))
        print(get_separator())
        
        comparison_data = []
        
        for mode in modes:
            # 使用选择器构建谱面查询条件
            where_clause, params = self.selector.build_chart_sql_where("c")
            
            # 覆盖模式筛选，使用当前循环的模式
            if "c.mode IN" in where_clause or "c.mode =" in where_clause:
                # 替换现有的模式条件
                where_clause = re.sub(r'c\.mode IN \(.*?\)|c\.mode = \?', f'c.mode = ?', where_clause)
                # 更新参数
                params = [p for p in params if not isinstance(p, int) or p not in modes]
                params.append(mode)
            else:
                where_clause += " AND c.mode = ?" if where_clause != "1=1" else "c.mode = ?"
                params.append(mode)
            
            cursor.execute(f"SELECT COUNT(*) FROM charts c WHERE {where_clause}", params)
            total_charts = cursor.fetchone()[0]
            
            cursor.execute(f"SELECT COUNT(DISTINCT c.creator_name) FROM charts c WHERE {where_clause} AND c.creator_name IS NOT NULL", params)
            unique_creators = cursor.fetchone()[0]
            
            cursor.execute(f"SELECT AVG(c.heat) FROM charts c WHERE {where_clause} AND c.heat > 0", params)
            avg_heat = cursor.fetchone()[0] or 0
            
            cursor.execute(f"SELECT AVG(CAST(c.level AS REAL)) FROM charts c WHERE {where_clause} AND c.level IS NOT NULL AND c.level != '' AND CAST(c.level AS REAL) > 0", params)
            avg_level = cursor.fetchone()[0] or 0
            
            cursor.execute(f"SELECT COUNT(*) FROM charts c WHERE {where_clause} AND c.status = 2", params)
            stable_charts = cursor.fetchone()[0]
            
            mode_name = self.mode_names.get(mode, "未知")
            comparison_data.append({
                'mode': mode,
                'name': mode_name,
                'total_charts': total_charts,
                'unique_creators': unique_creators,
                'avg_heat': avg_heat,
                'avg_level': avg_level,
                'stable_charts': stable_charts,
                'stability_rate': (stable_charts / total_charts * 100) if total_charts > 0 else 0
            })
        
        # 按总谱面数排序
        comparison_data.sort(key=lambda x: x['total_charts'], reverse=True)
        
        # 显示比较表格
        header = f"{'模式':<10} {'模式名':<12} {'总谱面':<8} {'创作者':<8} {'平均热度':<10} {'平均难度':<10} {'稳定率':<8}"
        print(header)
        print(get_separator())
        
        for data in comparison_data:
            mode_str = f"{data['mode']} ({data['name']})"
            print(f"{mode_str:<10} {data['name']:<12} {data['total_charts']:<8} {data['unique_creators']:<8} "
                f"{data['avg_heat']:<10.1f} {data['avg_level']:<10.1f} {data['stability_rate']:<8.1f}%")
        
        # 生成比较图表
        if len(modes) > 1:
            self._generate_comparison_chart(comparison_data)

    def _generate_comparison_chart(self, comparison_data):
        """生成模式比较图表"""
        modes = [f"{d['mode']}\n({d['name']})" for d in comparison_data]
        total_charts = [d['total_charts'] for d in comparison_data]
        unique_creators = [d['unique_creators'] for d in comparison_data]
        
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 6))
        
        # 左侧：总谱面数比较
        bars1 = ax1.bar(modes, total_charts, color='lightblue', alpha=0.7)
        ax1.set_title('各模式总谱面数比较\n筛选条件: ' + self.selector.get_current_selection())
        ax1.set_ylabel('谱面数量')
        ax1.tick_params(axis='x', rotation=45)
        
        # 添加数值标签
        for bar in bars1:
            height = bar.get_height()
            ax1.text(bar.get_x() + bar.get_width()/2., height + 0.1,
                    f'{int(height)}', ha='center', va='bottom')
        
        # 右侧：创作者数比较
        bars2 = ax2.bar(modes, unique_creators, color='lightgreen', alpha=0.7)
        ax2.set_title('各模式创作者数比较\n筛选条件: ' + self.selector.get_current_selection())
        ax2.set_ylabel('创作者数量')
        ax2.tick_params(axis='x', rotation=45)
        
        # 添加数值标签
        for bar in bars2:
            height = bar.get_height()
            ax2.text(bar.get_x() + bar.get_width()/2., height + 0.1,
                    f'{int(height)}', ha='center', va='bottom')
        
        plt.tight_layout()
        
        # 保存图表
        base_filename = "stb_mode_comparison.png"
        filename = self.get_unique_filename(base_filename, "png")
        filepath = os.path.join(self.output_dir, filename)
        plt.savefig(filepath, dpi=150, facecolor='white')
        plt.close()
        
        print(colorize(f"\n已生成模式比较图表: {filepath}", Colors.GREEN))
    
    @db_safe_operation
    def do_stb_stabled_by(self, arg):
        """
        查询玩家作为稳定者的谱面统计（支持选择器筛选）
        
        用法: stb_stabled_by <玩家名> [模式] [数量]
        参数:
        玩家名 - 作为稳定者的玩家名称
        模式   - 可选，模式编号，默认为当前模式
        数量   - 可选，要显示的谱面数量，默认为20
        
        示例:
        stb_stabled_by chuanyuan        # 查询chuanyuan作为稳定者的谱面
        stb_stabled_by chuanyuan 0 10   # 模式0前10个
        """
        args = arg.split()
        if not args:
            print(colorize("错误: 请输入玩家名", Colors.RED))
            return
        
        player_name = args[0]
        mode = self.current_mode
        limit = 20
        
        if len(args) > 1:
            try:
                mode = int(args[1])
                if len(args) > 2:
                    limit = int(args[2])
            except ValueError:
                print(colorize("错误: 请输入有效的数字", Colors.RED))
                return
        
        cursor = self.conn.cursor()
        
        # 构建查询条件：稳定者名称匹配
        where_conditions = ["c.stabled_by_name LIKE ?"]
        params = [f"%{player_name}%"]
        
        if mode != -1:
            where_conditions.append("c.mode = ?")
            params.append(mode)
        
        # 应用选择器的其他筛选（如难度、时间等）
        selector_where, selector_params = self.selector.build_chart_sql_where("c")
        if selector_where != "1=1":
            where_conditions.append(f"({selector_where})")
            params.extend(selector_params)
        
        where_clause = " AND ".join(where_conditions)
        
        query = f"""
        SELECT c.cid, s.title, s.artist, c.version, c.level, c.mode, c.status,
               c.heat, c.donate_count, c.play_count, c.last_updated
        FROM charts c
        JOIN songs s ON c.sid = s.sid
        WHERE {where_clause}
        ORDER BY c.heat DESC
        LIMIT ?
        """
        params.append(limit)
        
        cursor.execute(query, params)
        results = cursor.fetchall()
        
        if not results:
            print(colorize(f"\n没有找到 {player_name} 作为稳定者的谱面", Colors.YELLOW))
            return
        
        print(colorize(f"\n{player_name} 作为稳定者的谱面", Colors.CYAN))
        print(colorize(f"模式: {mode if mode!=-1 else '所有'}", Colors.YELLOW))
        print(get_separator())
        
        for cid, title, artist, version, level, m, status, heat, donate, play, updated in results:
            status_name = {0:"Alpha",1:"Beta",2:"Stable"}.get(status, "Unknown")
            mode_name = self.mode_names.get(m, "未知")
            print(f"{title} - {artist}")
            print(f"  CID:{cid} 模式:{m}({mode_name}) 难度:Lv.{level} 状态:{status_name}")
            print(f"  热度:{heat} 打赏:{donate} 游玩:{play}")
            print()
        
        print(get_separator())
        
        # 统计信息
        total = len(results)
        modes_dist = {}
        status_dist = {}
        for row in results:
            m = row[5]
            modes_dist[m] = modes_dist.get(m, 0) + 1
            status = row[6]
            status_dist[status] = status_dist.get(status, 0) + 1
        
        print(f"总计: {total} 个谱面")
        print("模式分布:", ", ".join([f"{self.mode_names.get(m,'未知')}:{c}" for m,c in modes_dist.items()]))
        print("状态分布:", ", ".join([f"{['Alpha','Beta','Stable'][s]}:{c}" for s,c in status_dist.items()]))
        
        # 生成图表
        chart_choice = input(colorize("\n是否生成统计图表? (y/N): ", Colors.CYAN)).lower()
        if chart_choice == 'y':
            self._generate_stabled_by_chart(results, player_name, f"模式 {mode if mode!=-1 else '所有'}", total)

    def _generate_stabled_by_chart(self, results, player_name, mode_str, total_count):
        """生成稳定者统计图表"""
        if not results:
            return
        
        titles = [row[1] for row in results]
        heats = [row[7] or 0 for row in results]
        levels = [row[4] for row in results]
        
        # 截断过长的标题
        display_titles = [t[:17]+"..." if len(t)>20 else t for t in titles]
        
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(18, 8))
        fig.suptitle(f'{player_name} 作为稳定者的谱面统计\n模式: {mode_str} | 总谱面数: {total_count}', 
                    fontsize=14, fontweight='bold')
        
        # 左侧：热度分布柱状图
        y_pos = range(len(display_titles))
        bars = ax1.barh(y_pos, heats, color='lightcoral', alpha=0.7)
        ax1.set_yticks(y_pos)
        ax1.set_yticklabels(display_titles)
        ax1.set_xlabel('热度')
        ax1.set_title('谱面热度分布')
        
        for bar, heat in zip(bars, heats):
            width = bar.get_width()
            ax1.text(width + 0.1, bar.get_y() + bar.get_height()/2, 
                    f'{heat}', ha='left', va='center', fontsize=9)
        
        # 右侧：难度分布饼图
        level_counts = {}
        for level in levels:
            if level:
                level_counts[level] = level_counts.get(level, 0) + 1
        
        if level_counts:
            level_labels = [f'Lv.{lvl}' for lvl in level_counts.keys()]
            level_values = list(level_counts.values())
            colors = plt.cm.Set3(np.linspace(0, 1, len(level_labels)))
            wedges, texts, autotexts = ax2.pie(level_values, labels=level_labels, autopct='%1.1f%%',
                                            colors=colors, startangle=90)
            for autotext in autotexts:
                autotext.set_color('white')
                autotext.set_fontweight('bold')
            ax2.set_title('难度分布')
        else:
            ax2.text(0.5, 0.5, '无难度数据', ha='center', va='center', transform=ax2.transAxes)
            ax2.set_title('难度分布')
        
        plt.tight_layout()
        
        safe_name = re.sub(r'[^\w]', '_', player_name)
        filename = self.get_unique_filename(f"stabled_by_{safe_name}.png", "png")
        filepath = os.path.join(self.output_dir, filename)
        plt.savefig(filepath, dpi=150, facecolor='white', bbox_inches='tight')
        plt.close()
        
        print(colorize(f"\n已生成稳定者统计图表: {filepath}", Colors.GREEN))

    @db_safe_operation
    def do_stb_top_stabilizers(self, arg):
        """
        显示顶级稳定者排行榜（审核上架谱面最多的玩家）
        
        用法: stb_top_stabilizers [模式] [数量]
        参数:
        模式 - 可选，模式编号，默认为所有模式
        数量 - 可选，要显示的稳定者数量，默认为20
        
        示例:
        stb_top_stabilizers        # 所有模式的顶级稳定者
        stb_top_stabilizers 0 10   # 模式0前10名稳定者
        """
        args = arg.split()
        mode = -1  # 默认所有模式
        limit = 20
        
        if args:
            try:
                mode = int(args[0])
                if mode not in self.mode_names:
                    print(colorize("错误: 无效的模式编号", Colors.RED))
                    return
                if len(args) > 1:
                    limit = int(args[1])
            except ValueError:
                print(colorize("错误: 请输入有效的数字", Colors.RED))
                return
        
        if limit <= 0:
            print(colorize("错误: 数量必须大于0", Colors.RED))
            return
        
        cursor = self.conn.cursor()
        
        try:
            # 构建查询条件
            where_conditions = ["c.stabled_by_name IS NOT NULL", "c.status = 2"]
            params = []
            
            # 模式筛选
            if mode != -1:
                where_conditions.append("c.mode = ?")
                params.append(mode)
            
            where_clause = " AND ".join(where_conditions)
            
            query = f"""
            SELECT 
                c.stabled_by_name,
                COUNT(*) as stable_count,
                AVG(c.heat) as avg_heat,
                MAX(c.heat) as max_heat,
                MIN(c.last_updated) as first_stable,
                MAX(c.last_updated) as last_stable
            FROM charts c
            WHERE {where_clause}
            GROUP BY c.stabled_by_name
            ORDER BY stable_count DESC, avg_heat DESC
            LIMIT ?
            """
            params.append(limit)
            
            cursor.execute(query, params)
            results = cursor.fetchall()
            
            if not results:
                mode_str = "所有模式" if mode == -1 else f"模式 {mode}"
                print(colorize(f"\n在{mode_str}中没有找到稳定者数据", Colors.YELLOW))
                return
            
            # 显示结果
            mode_str = "所有模式" if mode == -1 else f"模式 {mode} ({self.mode_names.get(mode, '未知')})"
            
            print(colorize(f"\n顶级稳定者排行榜", Colors.CYAN))
            print(colorize(f"模式: {mode_str}", Colors.YELLOW))
            print(get_separator())
            
            # 显示表头
            header_format = "{:<4} {:<20} {:<10} {:<10} {:<10} {:<12} {:<12}"
            print(colorize(header_format.format(
                "排名", "稳定者", "稳定谱面", "平均热度", "最高热度", "首次稳定", "最后稳定"
            ), Colors.BOLD))
            print(get_separator())
            
            # 显示数据
            for i, (stabilizer, count, avg_heat, max_heat, first_stable, last_stable) in enumerate(results, 1):
                # 处理过长的稳定者名
                display_stabilizer = stabilizer if len(stabilizer) <= 20 else stabilizer[:17] + "..."
                
                # 格式化日期
                def format_date(date_value):
                    if not date_value:
                        return "未知"
                    if isinstance(date_value, datetime):
                        return date_value.strftime('%Y-%m-%d')
                    elif isinstance(date_value, str):
                        return date_value[:10] if len(date_value) >= 10 else date_value
                    else:
                        return str(date_value)
                
                first_date = format_date(first_stable)
                last_date = format_date(last_stable)
                
                print(header_format.format(
                    f"#{i}",
                    display_stabilizer,
                    count,
                    f"{avg_heat:.1f}" if avg_heat else "N/A",
                    f"{max_heat:.0f}" if max_heat else "N/A",
                    first_date,
                    last_date
                ))
            
            print(get_separator())
            
            # 显示统计信息
            if results:
                total_stable = sum(row[1] for row in results)
                avg_stable = total_stable / len(results)
                max_stable = max(row[1] for row in results)
                
                print(colorize(f"\n统计信息:", Colors.BOLD))
                print(f"  总稳定谱面数: {total_stable}")
                print(f"  平均每人稳定谱面: {avg_stable:.1f}")
                print(f"  最高稳定谱面数: {max_stable}")
                
                # 生成图表的选项
                chart_choice = input(colorize("\n是否生成统计图表? (y/N): ", Colors.CYAN)).lower()
                if chart_choice == 'y':
                    self._generate_top_stabilizers_chart(results, mode_str)
                    
        except sqlite3.Error as e:
            print(colorize(f"数据库错误: {e}", Colors.RED))
        except Exception as e:
            print(colorize(f"操作错误: {e}", Colors.RED))

    def _generate_top_stabilizers_chart(self, results, mode_str):
        """生成顶级稳定者统计图表"""
        if not results:
            return
        
        stabilizers = [row[0] for row in results]
        counts = [row[1] for row in results]
        avg_heats = [row[2] if row[2] else 0 for row in results]
        max_heats = [row[3] if row[3] else 0 for row in results]
        
        # 截断过长的稳定者名
        display_stabilizers = [s[:12]+"..." if len(s)>15 else s for s in stabilizers]
        
        fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(20, 12))
        fig.suptitle(f'顶级稳定者统计\n模式: {mode_str}', fontsize=16, fontweight='bold')
        
        # 左上：稳定谱面数量柱状图
        y_pos = range(len(display_stabilizers))
        bars = ax1.barh(y_pos, counts, color='lightgreen', alpha=0.7)
        ax1.set_yticks(y_pos)
        ax1.set_yticklabels(display_stabilizers)
        ax1.set_xlabel('稳定谱面数量')
        ax1.set_title('稳定谱面数量排行')
        
        for bar, count in zip(bars, counts):
            width = bar.get_width()
            ax1.text(width + 0.1, bar.get_y() + bar.get_height()/2, 
                    f'{count}', ha='left', va='center', fontsize=9)
        
        # 右上：平均热度柱状图
        bars2 = ax2.barh(y_pos, avg_heats, color='lightcoral', alpha=0.7)
        ax2.set_yticks(y_pos)
        ax2.set_yticklabels(display_stabilizers)
        ax2.set_xlabel('平均热度')
        ax2.set_title('稳定谱面平均热度')
        
        for bar, heat in zip(bars2, avg_heats):
            width = bar.get_width()
            ax2.text(width + 0.1, bar.get_y() + bar.get_height()/2, 
                    f'{heat:.1f}', ha='left', va='center', fontsize=9)
        
        # 左下：最高热度柱状图
        bars3 = ax3.barh(y_pos, max_heats, color='gold', alpha=0.7)
        ax3.set_yticks(y_pos)
        ax3.set_yticklabels(display_stabilizers)
        ax3.set_xlabel('最高热度')
        ax3.set_title('稳定谱面最高热度')
        
        for bar, heat in zip(bars3, max_heats):
            width = bar.get_width()
            ax3.text(width + 0.1, bar.get_y() + bar.get_height()/2, 
                    f'{heat:.0f}', ha='left', va='center', fontsize=9)
        
        # 右下：散点图 - 稳定谱面数量 vs 平均热度
        scatter = ax4.scatter(counts, avg_heats, s=100, c=max_heats, 
                            cmap='viridis', alpha=0.7)
        ax4.set_xlabel('稳定谱面数量')
        ax4.set_ylabel('平均热度')
        ax4.set_title('稳定谱面数量 vs 平均热度 (颜色表示最高热度)')
        ax4.grid(True, alpha=0.3)
        
        for i, (stabilizer, count, heat) in enumerate(zip(display_stabilizers, counts, avg_heats)):
            ax4.annotate(stabilizer, (count, heat), xytext=(5, 5), 
                        textcoords='offset points', fontsize=8, alpha=0.7)
        
        cbar = plt.colorbar(scatter, ax=ax4)
        cbar.set_label('最高热度')
        
        plt.tight_layout()
        
        base_filename = "stb_top_stabilizers.png"
        filename = self.get_unique_filename(base_filename, "png")
        filepath = os.path.join(self.output_dir, filename)
        plt.savefig(filepath, dpi=150, facecolor='white', bbox_inches='tight')
        plt.close()
        
        print(colorize(f"\n已生成顶级稳定者统计图表: {filepath}", Colors.GREEN))

    @db_safe_operation
    def do_stb_creator_details(self, arg):
        """
        查看指定创作者的所有谱面统计

        用法: stb_creator_details <创作者名> [模式] [状态]
        参数:
        创作者名 - 要查询的创作者名称
        模式     - 可选，模式编号，默认为所有模式
        状态     - 可选，0=Alpha,1=Beta,2=Stable，默认全部

        示例:
        stb_creator_details chuanyuan
        stb_creator_details chuanyuan 0 2   # 模式0的Stable谱面
        """
        args = arg.split()
        if not args:
            print(colorize("错误: 请输入创作者名", Colors.RED))
            return
        creator = args[0]
        mode = self.current_mode
        status = None
        if len(args) > 1:
            try:
                mode = int(args[1])
            except:
                pass
        if len(args) > 2:
            try:
                status = int(args[2])
            except:
                pass

        # 构建选择器
        selector = copy.deepcopy(self.selector)
        selector.set_filters(players=[creator])
        if mode != -1:
            selector.set_filters(modes=[mode])
        if status is not None:
            selector.set_filters(statuses=[status])

        where_clause, params = selector.build_chart_sql_where("c")
        cursor = self.conn.cursor()

        # 获取创作者的总览
        query_total = f"""
        SELECT COUNT(*), COUNT(DISTINCT c.mode), AVG(c.heat), AVG(CAST(c.level AS REAL))
        FROM charts c
        WHERE {where_clause}
        """
        cursor.execute(query_total, params)
        total, modes_count, avg_heat, avg_level = cursor.fetchone()

        # 按状态分组
        query_status = f"""
        SELECT c.status, COUNT(*)
        FROM charts c
        WHERE {where_clause}
        GROUP BY c.status
        """
        cursor.execute(query_status, params)
        status_dist = cursor.fetchall()

        # 按模式分组
        query_mode = f"""
        SELECT c.mode, COUNT(*)
        FROM charts c
        WHERE {where_clause}
        GROUP BY c.mode
        ORDER BY c.mode
        """
        cursor.execute(query_mode, params)
        mode_dist = cursor.fetchall()

        # 显示结果
        print(colorize(f"\n创作者详情: {creator}", Colors.CYAN))
        print(get_separator())
        print(f"总谱面数: {colorize(total, Colors.GREEN)}")
        print(f"涉及模式数: {modes_count}")
        print(f"平均热度: {avg_heat:.1f}")
        print(f"平均难度: {avg_level:.1f}")

        if status_dist:
            print(colorize("\n状态分布:", Colors.BOLD))
            status_names = {0:"Alpha",1:"Beta",2:"Stable"}
            for s,c in status_dist:
                print(f"  {status_names.get(s, s)}: {c}")

        if mode_dist:
            print(colorize("\n模式分布:", Colors.BOLD))
            for m,c in mode_dist:
                mode_name = self.mode_names.get(m, "未知")
                print(f"  模式 {m}({mode_name}): {c}")

        # 可选的详细列表
        show_list = input(colorize("\n是否显示谱面列表? (y/N): ", Colors.CYAN)).lower()
        if show_list == 'y':
            query_list = f"""
            SELECT c.cid, s.title, c.version, c.level, c.status, c.heat
            FROM charts c JOIN songs s ON c.sid = s.sid
            WHERE {where_clause}
            ORDER BY c.heat DESC LIMIT 50
            """
            cursor.execute(query_list, params)
            charts = cursor.fetchall()
            print(colorize("\n谱面列表 (前50):", Colors.BOLD))
            for cid, title, ver, level, status, heat in charts:
                status_name = {0:"A",1:"B",2:"S"}.get(status, "?")
                print(f"  CID:{cid} [{status_name}] Lv.{level} {title} ({ver}) - 热度:{heat}")

        # 图表生成
        chart_choice = input(colorize("\n是否生成创作者统计图表? (y/N): ", Colors.CYAN)).lower()
        if chart_choice == 'y':
            self._generate_creator_chart(creator, status_dist, mode_dist)

    def _generate_creator_chart(self, creator, status_dist, mode_dist):
        """生成创作者统计图表"""
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14,6))
        fig.suptitle(f'创作者统计 - {creator}', fontsize=14)

        if status_dist:
            status_names = {0:"Alpha",1:"Beta",2:"Stable"}
            labels = [status_names.get(s, str(s)) for s,_ in status_dist]
            counts = [c for _,c in status_dist]
            ax1.pie(counts, labels=labels, autopct='%1.1f%%', startangle=90)
            ax1.set_title('状态分布')
        else:
            ax1.text(0.5,0.5,'无数据', ha='center', va='center', transform=ax1.transAxes)

        if mode_dist:
            mode_names = {0:"Key",1:"Step",2:"DJ",3:"Catch",4:"Pad",5:"Taiko",6:"Ring",7:"Slide",8:"Live",9:"Cube"}
            labels = [mode_names.get(m, str(m)) for m,_ in mode_dist]
            counts = [c for _,c in mode_dist]
            ax2.bar(labels, counts, color='lightblue')
            ax2.set_title('模式分布')
            ax2.set_ylabel('谱面数量')
        else:
            ax2.text(0.5,0.5,'无数据', ha='center', va='center', transform=ax2.transAxes)

        plt.tight_layout()
        safe_creator = re.sub(r'[^\w]', '_', creator)
        filename = self.get_unique_filename(f"creator_{safe_creator}.png", "png")
        filepath = os.path.join(self.output_dir, filename)
        plt.savefig(filepath, dpi=150, facecolor='white')
        plt.close()
        print(colorize(f"已生成创作者统计图表: {filepath}", Colors.GREEN))

    @db_safe_operation
    def do_stb_creator_trends(self, arg):
        """
        分析特定创作者的谱面更新趋势

        用法: stb_creator_trends <创作者名> [周期] [--since YYYY-MM-DD] [--last N(d|w|m|y)]
        周期: days(日), months(月), 默认months
        --since: 指定起始日期，格式 YYYY-MM-DD
        --last: 指定最近一段时间，如 30d (天), 8w (周), 6m (月), 1y (年)

        示例:
        stb_creator_trends chuanyuan
        stb_creator_trends chuanyuan days --last 90d
        stb_creator_trends chuanyuan months --since 2025-01-01
        """
        args = arg.split()
        if not args:
            print(colorize("错误: 请输入创作者名", Colors.RED))
            return

        creator = args[0]
        period = "months"
        time_range = None  # None 表示全部时间

        i = 1
        while i < len(args):
            if args[i] in ["days", "months"]:
                period = args[i]
                i += 1
            elif args[i] == "--since":
                if i+1 >= len(args):
                    print(colorize("错误: --since 需要指定日期 (YYYY-MM-DD)", Colors.RED))
                    return
                try:
                    start_date = datetime.strptime(args[i+1], "%Y-%m-%d")
                    time_range = {"start": start_date, "end": datetime.now()}
                    i += 2
                except ValueError:
                    print(colorize("错误: 日期格式应为 YYYY-MM-DD", Colors.RED))
                    return
            elif args[i] == "--last":
                if i+1 >= len(args):
                    print(colorize("错误: --last 需要指定时间范围 (如 30d, 6m)", Colors.RED))
                    return
                time_str = args[i+1]
                parsed = self._parse_time_range_string(time_str)
                if parsed:
                    time_range = parsed
                    i += 2
                else:
                    print(colorize(f"错误: 无法解析时间范围 '{time_str}'", Colors.RED))
                    return
            else:
                # 忽略未知参数
                i += 1

        selector = copy.deepcopy(self.selector)
        selector.set_filters(players=[creator])
        where_clause, params = selector.build_chart_sql_where("c")

        # 根据时间范围构建条件
        if time_range:
            # 使用用户指定的时间范围
            start = time_range['start']
            end = time_range['end']
            time_condition = "c.last_updated BETWEEN ? AND ?"
            params.extend([start, end])
            if where_clause != "1=1":
                where_clause += f" AND {time_condition}"
            else:
                where_clause = time_condition
        # 否则不添加时间条件（查询全部）

        # 根据周期设置分组
        if period == "days":
            group_by = "DATE(c.last_updated)"
            order_by = "DATE(c.last_updated)"
            x_label = "日期"
        else:
            group_by = "strftime('%Y-%m', c.last_updated)"
            order_by = "strftime('%Y-%m', c.last_updated)"
            x_label = "月份"

        query = f"""
        SELECT {group_by}, COUNT(*)
        FROM charts c
        WHERE {where_clause}
        GROUP BY {group_by}
        ORDER BY {order_by}
        """
        cursor = self.conn.cursor()
        cursor.execute(query, params)
        trend_data = cursor.fetchall()

        if not trend_data:
            print(colorize("没有找到趋势数据", Colors.YELLOW))
            return

        dates = [row[0] for row in trend_data]
        counts = [row[1] for row in trend_data]

        # 显示统计
        total = sum(counts)
        avg = total/len(counts)
        print(colorize(f"\n创作者 {creator} 的谱面更新趋势 ({period})", Colors.CYAN))
        if time_range:
            print(colorize(f"时间范围: {time_range['start'].strftime('%Y-%m-%d')} 至 {time_range['end'].strftime('%Y-%m-%d')}", Colors.YELLOW))
        else:
            print(colorize("时间范围: 全部时间", Colors.YELLOW))
        print(f"总更新谱面: {total}, 平均{period}更新: {avg:.1f}")

        # 生成图表
        fig, ax = plt.subplots(figsize=(12,6))
        ax.plot(dates, counts, 'o-', linewidth=2, markersize=6, color='#2196F3')
        ax.fill_between(dates, counts, alpha=0.3, color='#2196F3')
        ax.axhline(y=avg, color='red', linestyle='--', alpha=0.7, label=f'平均 {avg:.1f}')
        ax.set_title(f'创作者 {creator} 谱面更新趋势')
        ax.set_xlabel(x_label)
        ax.set_ylabel('更新谱面数量')
        ax.legend()
        ax.grid(True, alpha=0.3)
        plt.xticks(rotation=45)
        plt.tight_layout()

        safe_creator = re.sub(r'[^\w]', '_', creator)
        filename = self.get_unique_filename(f"creator_trends_{safe_creator}_{period}.png", "png")
        filepath = os.path.join(self.output_dir, filename)
        plt.savefig(filepath, dpi=150, facecolor='white')
        plt.close()
        print(colorize(f"已生成趋势图表: {filepath}", Colors.GREEN))

    def _parse_time_range_string(self, time_str):
        """解析时间范围字符串，支持格式：N(d|w|m|y) 或 YYYY-MM-DD"""
        now = datetime.now()
        try:
            if time_str.endswith('d'):
                days = int(time_str[:-1])
                return {'start': now - timedelta(days=days), 'end': now}
            elif time_str.endswith('w'):
                weeks = int(time_str[:-1])
                return {'start': now - timedelta(weeks=weeks), 'end': now}
            elif time_str.endswith('m'):
                months = int(time_str[:-1])
                return {'start': now - timedelta(days=months*30), 'end': now}
            elif time_str.endswith('y'):
                years = int(time_str[:-1])
                return {'start': now - timedelta(days=years*365), 'end': now}
            else:
                # 尝试解析为具体日期
                start = datetime.strptime(time_str, "%Y-%m-%d")
                return {'start': start, 'end': now}
        except:
            return None

    # 增强 do_update 命令


    def print_topics(self, header, cmds, cmdlen, maxcol):
        if cmds:
            self.stdout.write(colorize("%s\n" % str(header), Colors.CYAN))
            if self.ruler:
                self.stdout.write(colorize("%s\n" % str(self.ruler * len(header)), Colors.CYAN))
            self.columnize(cmds, maxcol-1)
            self.stdout.write("\n")


install_plugins(
    MalodyViz,
    colorize=colorize,
    colors=Colors,
    db_safe_operation=db_safe_operation,
    get_separator=get_separator,
    get_subseparator=get_subseparator,
    get_terminal_width=get_terminal_width,
    base_dir=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
)

def main() -> int:
    if not os.path.exists("malody_rankings.db"):
        print(colorize("Error: database file 'malody_rankings.db' not found", Colors.RED))
        print(colorize("Please place the database file in the project root directory", Colors.YELLOW))
        return 1

    try:
        MalodyViz().cmdloop()
        return 0
    except KeyboardInterrupt:
        print(colorize("\nInterrupted by user", Colors.YELLOW))
        return 130
    except Exception as e:
        print(colorize(f"\nProgram error: {e}", Colors.RED))
        return 1


if __name__ == "__main__":
    sys.exit(main())

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

    def do_compare(self, arg):
        """
        比较多个玩家的排名变化（参数优先）
        
        用法: compare <玩家1> <玩家2> [更多玩家...] [模式] [天数]
        参数:
        玩家1, 玩家2... - 要比较的玩家名称（优先于选择器）
        模式            - 可选，模式编号，默认为当前模式（优先于选择器）
        天数            - 可选，要查询的历史天数，默认为30天（优先于选择器）
        
        示例:
        compare Zani N0tYour1dol           # 比较两名玩家在当前模式最近30天的排名
        compare Zani N0tYour1dol -KIRITAN- 0 60  # 比较三名玩家在模式0最近60天的排名
        """
        args = arg.split()
        if len(args) < 2:
            print(colorize("错误: 请至少输入两个玩家名", Colors.RED))
            return
        
        players = []
        mode = self.current_mode
        days = 30
        i = 0
        
        # 解析参数中的玩家列表（优先于选择器）
        while i < len(args):
            if args[i].isdigit() and int(args[i]) in self.mode_names and int(args[i]) != -1:
                mode = int(args[i])
                i += 1
                break
            elif i > 0 and args[i].isdigit():
                days = int(args[i])
                i += 1
                break
            else:
                players.append(args[i])
                i += 1
        
        if i < len(args) and args[i].isdigit():
            days = int(args[i])
        
        if len(players) < 2:
            print(colorize("错误: 请至少输入两个玩家名", Colors.RED))
            return
        
        cursor = self.conn.cursor()
        
        # 使用参数中的天数，忽略选择器的时间筛选
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        
        fig, ax = plt.subplots(figsize=(12, 8))
        colors = plt.cm.Set3(np.linspace(0, 1, len(players)))
        
        for idx, player_name in enumerate(players):
            cursor.execute(
                "SELECT player_id FROM player_aliases WHERE alias = ?",
                (player_name,)
            )
            result = cursor.fetchone()
            
            if not result:
                print(colorize(f"\n未找到玩家: {player_name}", Colors.YELLOW))
                continue
            
            player_id = result[0]
            
            # 构建查询条件
            where_conditions = ["pr.player_id = ?", "pr.mode = ?", "pr.crawl_time >= ?"]
            query_params = [player_id, mode, start_date]
            
            where_clause = " AND ".join(where_conditions)
            
            cursor.execute(
                f"""
                SELECT pr.rank, pr.crawl_time
                FROM player_rankings pr
                WHERE {where_clause}
                ORDER BY pr.crawl_time
                """,
                query_params
            )
            
            history_data = cursor.fetchall()
            
            if not history_data:
                mode_name = self.mode_names.get(mode, "未知")
                print(colorize(f"\n玩家 {player_name} 在模式 {mode} ({mode_name}) 中最近 {days} 天没有数据", Colors.YELLOW))
                continue
            
            dates = [row[1] for row in history_data]
            ranks = [row[0] for row in history_data]
            
            ax.plot(dates, ranks, 'o-', linewidth=2, markersize=4, 
                color=colors[idx], label=player_name)
        
        ax.invert_yaxis()
        mode_name = self.mode_names.get(mode, "未知")
        
        # 修复字体颜色为黑色
        ax.set_title(f"Player Ranking Comparison (Mode {mode} - {mode_name})", color='black')
        ax.set_xlabel("Date", color='black')
        ax.set_ylabel("Rank", color='black')
        ax.grid(True, alpha=0.3)
        ax.legend()
        ax.tick_params(colors='black')
        
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
        ax.xaxis.set_major_locator(mdates.WeekdayLocator(interval=1))
        fig.autofmt_xdate()
        
        # 使用唯一文件名避免覆盖
        base_filename = f"player_comparison_mode{mode}.png"
        filename = self.get_unique_filename(base_filename, "png")
        filepath = os.path.join(self.output_dir, filename)
        plt.tight_layout()
        plt.savefig(filepath, dpi=150, facecolor='white')
        plt.close()
        
        print(colorize(f"\n已生成玩家比较图表: {filepath}", Colors.GREEN))
    
    @db_safe_operation
    def do_top_chart(self, arg):
        """
        生成顶级玩家分布图表
        
        用法: top_chart [数量] [模式]
        参数:
          数量 - 可选，要显示的玩家数量，默认为20
          模式 - 可选，模式编号，默认为当前模式
        
        示例:
          top_chart        # 生成当前模式前20名玩家的图表
          top_chart 10 0   # 生成模式0前10名玩家的图表
        """
        args = arg.split()
        limit = 20
        mode = self.current_mode
        
        if args:
            try:
                if int(args[0]) in self.mode_names:
                    mode = int(args[0])
                    if len(args) > 1:
                        limit = int(args[1])
                else:
                    limit = int(args[0])
                    if len(args) > 1 and int(args[1]) in self.mode_names:
                        mode = int(args[1])
            except ValueError:
                print(colorize("错误: 请输入有效的数字", Colors.RED))
                return
        
        if limit <= 0:
            print(colorize("错误: 数量必须大于0", Colors.RED))
            return
        
        cursor = self.conn.cursor()
        
        cursor.execute(
            "SELECT MAX(crawl_time) FROM player_rankings WHERE mode = ?",
            (mode,)
        )
        latest_time = cursor.fetchone()[0]
        
        if not latest_time:
            mode_name = self.mode_names.get(mode, "未知")
            print(colorize(f"\n模式 {mode} ({mode_name}) 没有数据", Colors.YELLOW))
            return
        
        cursor.execute(
            """
            SELECT pr.rank, pr.name, pr.acc, pr.exp
            FROM player_rankings pr
            WHERE pr.mode = ? AND pr.crawl_time = ?
            ORDER BY pr.rank
            LIMIT ?
            """,
            (mode, latest_time, limit)
        )
        
        players = cursor.fetchall()
        
        if not players:
            mode_name = self.mode_names.get(mode, "未知")
            print(colorize(f"\n模式 {mode} ({mode_name}) 没有找到玩家数据", Colors.YELLOW))
            return
        
        ranks = [p[0] for p in players]
        names = [p[1] for p in players]
        accuracies = [p[2] for p in players]
        exps = [p[3] for p in players]
        
        # 创建更大的图表以适应更多玩家名
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(20, 12))
        
        # 设置图表背景和字体颜色
        fig.patch.set_facecolor('white')
        
        # 准确率图表
        max_acc = max(accuracies)
        acc_diffs = [max_acc - acc for acc in accuracies]
        
        bars = ax1.bar(range(len(players)), acc_diffs, color=plt.cm.viridis(np.linspace(0, 1, len(players))))
        mode_name = self.mode_names.get(mode, "未知")
        
        # 修复字体颜色为黑色
        ax1.set_title(f"Mode {mode} ({mode_name}) Top {limit} Players Accuracy Difference", color='black')
        ax1.set_xlabel("Rank", color='black')
        ax1.set_ylabel("Accuracy Difference from Max (%)", color='black')
        ax1.set_xticks(range(len(players)))
        ax1.set_xticklabels(ranks, rotation=45)
        ax1.tick_params(colors='black')
        ax1.invert_yaxis()
        
        # 智能数据标签布局 - 避免重叠
        def smart_label_placement(ax, bars, values, y_offset_factor=0.01, rotation=45):
            """智能放置数据标签以避免重叠"""
            max_val = max(values) if values else 1
            y_offset = max_val * y_offset_factor
            
            # 收集所有标签位置
            label_positions = []
            for i, (bar, value) in enumerate(zip(bars, values)):
                x = bar.get_x() + bar.get_width() / 2
                y = bar.get_height() + y_offset
                label_positions.append((x, y, value, i))
            
            # 按y值排序，从高到低处理
            label_positions.sort(key=lambda pos: pos[1], reverse=True)
            
            # 调整重叠的标签
            adjusted_positions = []
            min_vertical_spacing = max_val * 0.05  # 最小垂直间距
            
            for x, y, value, idx in label_positions:
                # 检查是否与已放置的标签重叠
                overlap = False
                for adj_x, adj_y, _, _ in adjusted_positions:
                    if abs(x - adj_x) < 0.3 and abs(y - adj_y) < min_vertical_spacing:
                        overlap = True
                        break
                
                if overlap:
                    # 如果有重叠，稍微调整y位置
                    y_adjust = min_vertical_spacing
                    while any(abs(x - adj_x) < 0.3 and abs(y + y_adjust - adj_y) < min_vertical_spacing 
                             for adj_x, adj_y, _, _ in adjusted_positions):
                        y_adjust += min_vertical_spacing
                    y += y_adjust
                
                adjusted_positions.append((x, y, value, idx))
            
            # 按原始索引排序并添加标签
            adjusted_positions.sort(key=lambda pos: pos[3])
            
            for x, y, value, idx in adjusted_positions:
                ax.text(x, y, f'{value:.2f}%', 
                       ha='center', va='bottom', fontsize=8,
                       color='black', rotation=rotation,
                       bbox=dict(boxstyle='round,pad=0.2', facecolor='white', alpha=0.7, edgecolor='none'))
        
        # 使用智能标签布局
        smart_label_placement(ax1, bars, accuracies, y_offset_factor=0.02, rotation=45)
        
        # 在x轴下方添加玩家名字，使用更智能的布局
        name_y_pos = -0.08 * max(acc_diffs) if max(acc_diffs) > 0 else -0.1
        
        for i, (bar, name) in enumerate(zip(bars, names)):
            # 截断过长的名字
            display_name = name if len(name) <= 12 else name[:10] + '...'
            ax1.text(bar.get_x() + bar.get_width()/2., name_y_pos,
                    display_name, ha='right', va='top', fontsize=7, 
                    rotation=60, color='black')
        
        # 经验值图表
        exp_bars = ax2.bar(range(len(players)), exps, color=plt.cm.plasma(np.linspace(0, 1, len(players))))
        ax2.set_title(f"Mode {mode} ({mode_name}) Top {limit} Players Experience", color='black')
        ax2.set_xlabel("Rank", color='black')
        ax2.set_ylabel("Experience", color='black')
        ax2.set_xticks(range(len(players)))
        ax2.set_xticklabels(ranks, rotation=45)
        ax2.set_yscale('log')
        ax2.tick_params(colors='black')
        
        # 改进对数坐标轴的刻度标注
        def log_format_func(value, pos=None):
            if value >= 1000000:
                return f'{value/1000000:.1f}M'
            elif value >= 1000:
                return f'{value/1000:.0f}k'
            elif value >= 100:
                return f'{value:.0f}'
            else:
                return f'{value:.0f}'
        
        # 设置y轴格式
        ax2.yaxis.set_major_formatter(FuncFormatter(log_format_func))
        
        # 计算合适的刻度范围
        min_exp = min(exps) if exps else 1
        max_exp = max(exps) if exps else 1000
        
        # 生成更细分的刻度值
        min_power = math.floor(math.log10(min_exp))
        max_power = math.ceil(math.log10(max_exp))
        
        tick_values = []
        for power in range(int(min_power), int(max_power) + 1):
            base = 10 ** power
            tick_values.extend([base * mult for mult in [1, 2, 5] 
                              if min_exp <= base * mult <= max_exp * 1.1])
        
        # 设置刻度
        ax2.set_yticks(tick_values)
        
        # 添加网格线
        ax2.grid(True, which='both', alpha=0.3)
        
        # 智能放置经验值标签
        def smart_exp_label_placement(ax, bars, values, rotation=45):
            """智能放置经验值标签"""
            if not values:
                return
                
            # 使用对数空间计算偏移
            log_values = [math.log10(v) for v in values]
            max_log = max(log_values)
            log_offset = 0.05 * (max_log - min(log_values)) if len(log_values) > 1 else 0.1
            
            label_positions = []
            for i, (bar, value, log_val) in enumerate(zip(bars, values, log_values)):
                x = bar.get_x() + bar.get_width() / 2
                y_log = log_val + log_offset
                y = 10 ** y_log
                label_positions.append((x, y, value, i))
            
            # 按y值排序，从高到低处理
            label_positions.sort(key=lambda pos: pos[1], reverse=True)
            
            # 调整重叠的标签（在对数空间中）
            adjusted_positions = []
            min_log_spacing = 0.08  # 对数空间中的最小间距
            
            for x, y, value, idx in label_positions:
                log_y = math.log10(y)
                overlap = False
                for adj_x, adj_y, _, _ in adjusted_positions:
                    adj_log_y = math.log10(adj_y)
                    if abs(x - adj_x) < 0.3 and abs(log_y - adj_log_y) < min_log_spacing:
                        overlap = True
                        break
                
                if overlap:
                    # 在对数空间中调整
                    log_adjust = min_log_spacing
                    while any(abs(x - adj_x) < 0.3 and 
                             abs(log_y + log_adjust - math.log10(adj_y)) < min_log_spacing
                             for adj_x, adj_y, _, _ in adjusted_positions):
                        log_adjust += min_log_spacing
                    y = 10 ** (log_y + log_adjust)
                
                adjusted_positions.append((x, y, value, idx))
            
            # 按原始索引排序并添加标签
            adjusted_positions.sort(key=lambda pos: pos[3])
            
            for x, y, value, idx in adjusted_positions:
                ax.text(x, y, f'{value:.0f}', 
                       ha='center', va='bottom', fontsize=8,
                       color='black', rotation=rotation,
                       bbox=dict(boxstyle='round,pad=0.2', facecolor='white', alpha=0.7, edgecolor='none'))
        
        # 使用智能经验值标签布局
        smart_exp_label_placement(ax2, exp_bars, exps, rotation=45)
        
        # 在x轴下方添加玩家名字
        name_log_pos = math.log10(min_exp) - 0.3 if min_exp > 0 else 0
        name_y_pos = 10 ** name_log_pos
        
        for i, (bar, name) in enumerate(zip(exp_bars, names)):
            # 截断过长的名字
            display_name = name if len(name) <= 12 else name[:10] + '...'
            ax2.text(bar.get_x() + bar.get_width()/2., name_y_pos,
                    display_name, ha='right', va='top', fontsize=7, 
                    rotation=60, color='black')
        
        # 根据玩家数量调整布局
        bottom_margin = 0.25 + 0.01 * limit  # 动态调整底部边距
        plt.subplots_adjust(bottom=min(bottom_margin, 0.4), top=0.9, wspace=0.3)
        
        plt.tight_layout()
        
        # 使用唯一文件名避免覆盖
        base_filename = f"top_players_mode{mode}.png"
        filename = self.get_unique_filename(base_filename, "png")
        filepath = os.path.join(self.output_dir, filename)
        plt.savefig(filepath, dpi=150, facecolor='white', bbox_inches='tight')
        plt.close()
        
        print(colorize(f"\n已生成顶级玩家分布图表: {filepath}", Colors.GREEN))
        print(colorize(f"图表尺寸已调整为适应 {limit} 名玩家", Colors.YELLOW))
    
    @db_safe_operation
    def do_trend(self, arg):
        """
        统计玩家数据变化趋势（参数优先）

        用法: trend <起始日期> [--mode 模式] [--fields 字段列表] [--match 时间窗口] [--rank-range 范围]
        选项:
            --mode        模式编号，默认为当前模式
            --fields      要显示的统计项，用逗号分隔，如 rank,lv,exp,acc,combo,pc
            --match       匹配时间窗口，如 1h(1小时), 30m(30分钟), 7d(7天)，默认1h
            --rank-range  排行榜名次范围，如 1-100，默认1-50

        示例:
            trend 2024-01-01
            trend 2024-01-01 0
            trend 2024-01-01 --match 2h --rank-range 1-50
            trend 2024-01-01 --mode 0 --fields rank,exp,acc
        """
        import re
        from datetime import timedelta

        # 合法字段列表
        valid_fields = ["rank", "lv", "exp", "acc", "combo", "pc"]

        # 辅助函数：解析时间窗口字符串
        def parse_time_window(s):
            s = s.strip().lower()
            match = re.match(r'^(\d+)([dhms])$', s)
            if not match:
                raise ValueError(f"无效的时间窗口格式: {s}，应为数字后跟 d/h/m/s")
            num = int(match.group(1))
            unit = match.group(2)
            if unit == 'd':
                return timedelta(days=num)
            elif unit == 'h':
                return timedelta(hours=num)
            elif unit == 'm':
                return timedelta(minutes=num)
            elif unit == 's':
                return timedelta(seconds=num)
            else:
                raise ValueError(f"未知时间单位: {unit}")

        # 解析参数
        args_list = arg.split()
        start_date_str = None
        mode = self.current_mode
        display_fields = valid_fields[:]  # 默认显示所有字段
        match_window = timedelta(hours=1)  # 默认1小时
        rank_range = None  # (min, max) 或 None

        # 解析位置参数和选项
        i = 0
        while i < len(args_list):
            token = args_list[i]
            if token.startswith('--'):
                # 选项
                if token == '--mode':
                    if i+1 >= len(args_list):
                        print(colorize("错误: --mode 需要指定模式编号", Colors.RED))
                        return
                    try:
                        mode = int(args_list[i+1])
                        if mode not in self.mode_names or mode == -1:
                            print(colorize(f"错误: 无效的模式编号 {mode}", Colors.RED))
                            return
                    except ValueError:
                        print(colorize("错误: --mode 参数必须是数字", Colors.RED))
                        return
                    i += 2
                elif token == '--fields':
                    if i+1 >= len(args_list):
                        print(colorize("错误: --fields 需要指定字段列表", Colors.RED))
                        return
                    fields_str = args_list[i+1]
                    display_fields = [f.strip() for f in fields_str.split(',')]
                    # 验证字段
                    invalid = [f for f in display_fields if f not in valid_fields]
                    if invalid:
                        print(colorize(f"错误: 无效的显示项: {', '.join(invalid)}", Colors.RED))
                        print(colorize(f"有效的显示项: {', '.join(valid_fields)}", Colors.YELLOW))
                        return
                    i += 2
                elif token == '--match':
                    if i+1 >= len(args_list):
                        print(colorize("错误: --match 需要指定时间窗口", Colors.RED))
                        return
                    try:
                        match_window = parse_time_window(args_list[i+1])
                    except ValueError as e:
                        print(colorize(f"错误: {e}", Colors.RED))
                        return
                    i += 2
                elif token == '--rank-range':
                    if i+1 >= len(args_list):
                        print(colorize("错误: --rank-range 需要指定范围，如 1-100", Colors.RED))
                        return
                    range_str = args_list[i+1]
                    try:
                        parts = range_str.split('-')
                        if len(parts) != 2:
                            raise ValueError
                        min_rank = int(parts[0])
                        max_rank = int(parts[1])
                        if min_rank <= 0 or max_rank <= 0 or min_rank > max_rank:
                            raise ValueError
                        rank_range = (min_rank, max_rank)
                    except:
                        print(colorize("错误: --rank-range 格式应为 min-max，例如 1-100", Colors.RED))
                        return
                    i += 2
                else:
                    print(colorize(f"错误: 未知选项 {token}", Colors.RED))
                    return
            else:
                # 位置参数：起始日期，模式，显示字段（向后兼容）
                if start_date_str is None:
                    start_date_str = token
                elif mode == self.current_mode and not any(f in token for f in valid_fields) and token.isdigit():
                    # 如果模式还是默认且下一个是数字，可能是模式
                    try:
                        mode = int(token)
                        if mode not in self.mode_names or mode == -1:
                            print(colorize(f"错误: 无效的模式编号 {mode}", Colors.RED))
                            return
                    except ValueError:
                        # 不是数字，可能是显示字段的一部分
                        pass
                else:
                    # 可能是显示字段
                    display_fields = [f.strip() for f in token.split(',')]
                    invalid = [f for f in display_fields if f not in valid_fields]
                    if invalid:
                        print(colorize(f"错误: 无效的显示项: {', '.join(invalid)}", Colors.RED))
                        print(colorize(f"有效的显示项: {', '.join(valid_fields)}", Colors.YELLOW))
                        return
                i += 1

        if start_date_str is None:
            print(colorize("错误: 请输入起始日期 (YYYY-MM-DD)", Colors.RED))
            return
        try:
            start_date = datetime.strptime(start_date_str, "%Y-%m-%d")
        except ValueError:
            print(colorize("错误: 日期格式应为 YYYY-MM-DD", Colors.RED))
            return

        # 再次验证字段（避免遗漏）
        if any(f not in valid_fields for f in display_fields):
            print(colorize("错误: 无效的显示项", Colors.RED))
            return

        cursor = self.conn.cursor()

        # 获取数据库最新时间
        if mode != -1:
            cursor.execute("SELECT MAX(crawl_time) FROM player_rankings WHERE mode = ?", (mode,))
        else:
            cursor.execute("SELECT MAX(crawl_time) FROM player_rankings")
        latest_time_row = cursor.fetchone()
        if not latest_time_row or latest_time_row[0] is None:
            print(colorize("错误: 数据库中没有数据，无法进行趋势分析", Colors.RED))
            return

        raw_end_point = latest_time_row[0]
        # 确保 end_point 是 datetime 类型
        if isinstance(raw_end_point, str):
            try:
                end_point = datetime.fromisoformat(raw_end_point)
            except ValueError:
                # 尝试常见格式
                end_point = datetime.strptime(raw_end_point, '%Y-%m-%d %H:%M:%S')
        else:
            end_point = raw_end_point

        # 设置默认排名范围
        if rank_range is None:
            rank_range = (1, 50)
            print(colorize("未指定排名范围，默认使用 1-50", Colors.YELLOW))

        # 确保起始日期不晚于最新时间
        if start_date > end_point:
            print(colorize(f"错误: 起始日期 {start_date.strftime('%Y-%m-%d')} 晚于数据库最新时间 {end_point.strftime('%Y-%m-%d')}", Colors.RED))
            return

        # 匹配窗口基于最新时间向前推
        window_start = end_point - match_window

        # 构建基础模式条件
        mode_condition = "mode = ?" if mode != -1 else "1=1"
        params_start = [mode] if mode != -1 else []
        params_end = [mode] if mode != -1 else []

        # 起始快照：起始日期之前最近一条记录（不考虑窗口，仅用于对比）
        if mode != -1:
            cursor.execute("""
                SELECT pr.player_id, pr.name, pr.rank, pr.lv, pr.exp, pr.acc, pr.combo, pr.pc
                FROM player_rankings pr
                INNER JOIN (
                    SELECT player_id, MAX(crawl_time) as max_time
                    FROM player_rankings
                    WHERE mode = ? AND crawl_time <= ?
                    GROUP BY player_id
                ) latest ON pr.player_id = latest.player_id AND pr.crawl_time = latest.max_time
                WHERE pr.mode = ?
            """, (mode, start_date, mode))
        else:
            cursor.execute("""
                SELECT pr.player_id, pr.name, pr.rank, pr.lv, pr.exp, pr.acc, pr.combo, pr.pc
                FROM player_rankings pr
                INNER JOIN (
                    SELECT player_id, MAX(crawl_time) as max_time
                    FROM player_rankings
                    WHERE crawl_time <= ?
                    GROUP BY player_id
                ) latest ON pr.player_id = latest.player_id AND pr.crawl_time = latest.max_time
            """, (start_date,))
        start_players = {}
        for row in cursor.fetchall():
            pid = row[0]
            start_players[pid] = (row[1], row[2], row[3], row[4], row[5], row[6], row[7])

        # 结束快照：匹配窗口内最新记录（窗口内无记录视为掉出榜）
        if mode != -1:
            cursor.execute("""
                SELECT pr.player_id, pr.name, pr.rank, pr.lv, pr.exp, pr.acc, pr.combo, pr.pc, pr.crawl_time
                FROM player_rankings pr
                INNER JOIN (
                    SELECT player_id, MAX(crawl_time) as max_time
                    FROM player_rankings
                    WHERE mode = ? AND crawl_time BETWEEN ? AND ?
                    GROUP BY player_id
                ) latest ON pr.player_id = latest.player_id AND pr.crawl_time = latest.max_time
                WHERE pr.mode = ?
            """, (mode, window_start, end_point, mode))
        else:
            cursor.execute("""
                SELECT pr.player_id, pr.name, pr.rank, pr.lv, pr.exp, pr.acc, pr.combo, pr.pc, pr.crawl_time
                FROM player_rankings pr
                INNER JOIN (
                    SELECT player_id, MAX(crawl_time) as max_time
                    FROM player_rankings
                    WHERE crawl_time BETWEEN ? AND ?
                    GROUP BY player_id
                ) latest ON pr.player_id = latest.player_id AND pr.crawl_time = latest.max_time
            """, (window_start, end_point))
        end_players = {}
        latest_times = {}  # 存储每个玩家的最新记录时间（用于显示）
        for row in cursor.fetchall():
            pid = row[0]
            end_players[pid] = (row[1], row[2], row[3], row[4], row[5], row[6], row[7])
            latest_times[pid] = row[8]

        # 如果指定了排名范围，过滤起始和结束玩家
        if rank_range:
            min_rank, max_rank = rank_range
            # 过滤起始玩家
            start_players = {pid: data for pid, data in start_players.items()
                             if min_rank <= data[1] <= max_rank}
            # 过滤结束玩家
            end_players = {pid: data for pid, data in end_players.items()
                           if min_rank <= data[1] <= max_rank}
            # 对于掉出榜的玩家（仅在start中），需要判断其起始排名是否在范围内
            # 对于新上榜的玩家（仅在end中），结束排名已在范围内
            # 对于一直在榜的玩家，起始和结束都在范围内

        # 分析变化
        all_player_ids = set(start_players.keys()) | set(end_players.keys())

        trend_data = []

        for player_id in all_player_ids:
            in_start = player_id in start_players
            in_end = player_id in end_players

            if in_start and in_end:
                # 一直在榜
                start_data = start_players[player_id]
                end_data = end_players[player_id]
                start_name, start_rank, start_lv, start_exp, start_acc, start_combo, start_pc = start_data
                end_name, end_rank, end_lv, end_exp, end_acc, end_combo, end_pc = end_data
                current_name = end_name if end_name != start_name else start_name

                # 检查指定字段是否有变化
                field_has_changes = False
                for field in display_fields:
                    if field == "rank" and start_rank != end_rank:
                        field_has_changes = True
                        break
                    elif field == "lv" and start_lv != end_lv:
                        field_has_changes = True
                        break
                    elif field == "exp" and start_exp != end_exp:
                        field_has_changes = True
                        break
                    elif field == "acc" and start_acc != end_acc:
                        field_has_changes = True
                        break
                    elif field == "combo" and start_combo != end_combo:
                        field_has_changes = True
                        break
                    elif field == "pc" and start_pc != end_pc:
                        field_has_changes = True
                        break

                if not field_has_changes:
                    continue

                trend_data.append({
                    'player_id': player_id,
                    'name': current_name,
                    'status': '=',
                    'start_rank': start_rank,
                    'end_rank': end_rank,
                    'rank_change': end_rank - start_rank,
                    'start_lv': start_lv,
                    'end_lv': end_lv,
                    'lv_change': end_lv - start_lv,
                    'start_exp': start_exp,
                    'end_exp': end_exp,
                    'exp_change': end_exp - start_exp,
                    'start_acc': start_acc,
                    'end_acc': end_acc,
                    'acc_change': end_acc - start_acc,
                    'start_combo': start_combo,
                    'end_combo': end_combo,
                    'combo_change': end_combo - start_combo,
                    'start_pc': start_pc,
                    'end_pc': end_pc,
                    'pc_change': end_pc - start_pc,
                    'has_changes': True,
                    'latest_time': latest_times.get(player_id)
                })
            elif in_start and not in_end:
                # 掉出榜：起始玩家在范围内，但窗口内无记录
                start_data = start_players[player_id]
                start_name, start_rank, start_lv, start_exp, start_acc, start_combo, start_pc = start_data

                trend_data.append({
                    'player_id': player_id,
                    'name': start_name,
                    'status': '-',
                    'start_rank': start_rank,
                    'end_rank': None,
                    'rank_change': None,
                    'start_lv': start_lv,
                    'end_lv': None,
                    'lv_change': None,
                    'start_exp': start_exp,
                    'end_exp': None,
                    'exp_change': None,
                    'start_acc': start_acc,
                    'end_acc': None,
                    'acc_change': None,
                    'start_combo': start_combo,
                    'end_combo': None,
                    'combo_change': None,
                    'start_pc': start_pc,
                    'end_pc': None,
                    'pc_change': None,
                    'has_changes': True,
                    'latest_time': None
                })
            elif not in_start and in_end:
                # 新上榜：结束玩家在范围内
                end_data = end_players[player_id]
                end_name, end_rank, end_lv, end_exp, end_acc, end_combo, end_pc = end_data

                trend_data.append({
                    'player_id': player_id,
                    'name': end_name,
                    'status': '+',
                    'start_rank': None,
                    'end_rank': end_rank,
                    'rank_change': None,
                    'start_lv': None,
                    'end_lv': end_lv,
                    'lv_change': None,
                    'start_exp': None,
                    'end_exp': end_exp,
                    'exp_change': None,
                    'start_acc': None,
                    'end_acc': end_acc,
                    'acc_change': None,
                    'start_combo': None,
                    'end_combo': end_combo,
                    'combo_change': None,
                    'start_pc': None,
                    'end_pc': end_pc,
                    'pc_change': None,
                    'has_changes': True,
                    'latest_time': latest_times.get(player_id)
                })

        if not trend_data:
            print(colorize(f"\n在指定的时间范围内，模式 {mode} 没有发现数据变化", Colors.YELLOW))
            return

        # 按结束排名排序（掉出榜的玩家排最后）
        trend_data.sort(key=lambda x: (x['end_rank'] is None, x['end_rank'] or 9999))

        # 显示结果
        mode_name = self.mode_names.get(mode, "未知")
        print(colorize(f"\n玩家数据变化趋势 (模式 {mode} - {mode_name})", Colors.CYAN))
        print(colorize(f"筛选条件: {self.selector.get_current_selection()}", Colors.YELLOW))
        if rank_range:
            print(colorize(f"排名范围: {rank_range[0]} - {rank_range[1]}", Colors.YELLOW))
        print(colorize(f"起始时间: {start_date.strftime('%Y-%m-%d')}", Colors.YELLOW))
        print(colorize(f"数据截止时间: {end_point.strftime('%Y-%m-%d %H:%M:%S')}", Colors.YELLOW))
        print(colorize(f"匹配窗口: {match_window} (基于数据库最新数据向前推)", Colors.YELLOW))

        separator_width = get_terminal_width()
        print(get_separator(separator_width))

        # 构建表头
        header_parts = ["状态", "玩家名"]
        format_specs = [8, 20]

        field_configs = {
            "rank": ("排名", 10, 10, 10),
            "lv": ("等级", 10, 10, 10),
            "exp": ("经验", 12, 12, 10),
            "acc": ("准确率", 12, 12, 12),
            "combo": ("连击", 10, 10, 10),
            "pc": ("游玩", 10, 10, 10)
        }

        for field in display_fields:
            if field in field_configs:
                name, start_width, end_width, change_width = field_configs[field]
                header_parts.extend([f"起始{name}", f"结束{name}", f"{name}变化"])
                format_specs.extend([start_width, end_width, change_width])

        # 调整玩家名宽度
        total_width = sum(format_specs) + (len(format_specs) - 1) * 2
        if total_width > separator_width:
            excess = total_width - separator_width
            player_width = max(10, 20 - excess)
            format_specs[1] = player_width

        format_parts = [f"{{:<{w}}}" for w in format_specs]
        header_format = "  ".join(format_parts)
        print(colorize(header_format.format(*header_parts), Colors.BOLD))
        print(get_separator(separator_width))

        for player in trend_data:
            row_parts = []
            # 状态符号
            if player['status'] == '+':
                status_display = colorize("[+]", Colors.GREEN)
            elif player['status'] == '-':
                status_display = colorize("[-]", Colors.RED)
            else:
                status_display = colorize("[=]", Colors.BLUE)

            player_name = player['name']
            max_name_len = format_specs[1]
            if len(player_name) > max_name_len:
                player_name = player_name[:max_name_len-3] + "..."
            row_parts.extend([status_display, player_name])

            for field in display_fields:
                if field == "rank":
                    row_parts.extend([
                        str(player['start_rank']) if player['start_rank'] is not None else "N/A",
                        str(player['end_rank']) if player['end_rank'] is not None else "掉出",
                        format_change(player['rank_change'], reverse=True)
                    ])
                elif field == "lv":
                    row_parts.extend([
                        str(player['start_lv']) if player['start_lv'] is not None else "N/A",
                        str(player['end_lv']) if player['end_lv'] is not None else "N/A",
                        format_change(player['lv_change'])
                    ])
                elif field == "exp":
                    row_parts.extend([
                        format_number(player['start_exp']) if player['start_exp'] is not None else "N/A",
                        format_number(player['end_exp']) if player['end_exp'] is not None else "N/A",
                        format_change(player['exp_change'])
                    ])
                elif field == "acc":
                    row_parts.extend([
                        f"{player['start_acc']:.2f}%" if player['start_acc'] is not None else "N/A",
                        f"{player['end_acc']:.2f}%" if player['end_acc'] is not None else "N/A",
                        format_change(player['acc_change'], is_percent=True)
                    ])
                elif field == "combo":
                    row_parts.extend([
                        format_number(player['start_combo']) if player['start_combo'] is not None else "N/A",
                        format_number(player['end_combo']) if player['end_combo'] is not None else "N/A",
                        format_change(player['combo_change'])
                    ])
                elif field == "pc":
                    row_parts.extend([
                        format_number(player['start_pc']) if player['start_pc'] is not None else "N/A",
                        format_number(player['end_pc']) if player['end_pc'] is not None else "N/A",
                        format_change(player['pc_change'])
                    ])

            print(header_format.format(*row_parts))

        print(get_separator(separator_width))

        total_players = len(trend_data)
        stayed = len([p for p in trend_data if p['status'] == '='])
        dropped = len([p for p in trend_data if p['status'] == '-'])
        new = len([p for p in trend_data if p['status'] == '+'])

        print(colorize(f"统计: 总计 {total_players} 名玩家 | 一直在榜: {stayed} | 掉出榜: {dropped} | 新上榜: {new}", Colors.YELLOW))

        # 导出选项
        export_choice = input(colorize("\n是否导出为CSV文件? (y/N): ", Colors.CYAN)).lower()
        if export_choice == 'y':
            self.export_trend_data(trend_data, display_fields, mode, start_date, end_point)

    # 注意：export_trend_data 方法需要更新以接受 start_date 和 end_point
    def export_trend_data(self, trend_data, display_fields, mode, start_date, end_point):
        """导出趋势数据为CSV文件"""
        # 构建数据框
        data_dict = {}
        
        # 基本字段
        data_dict['状态'] = [player['status'] for player in trend_data]
        data_dict['玩家名'] = [player['name'] for player in trend_data]
        
        # 根据选择的字段添加数据
        if "rank" in display_fields:
            data_dict['起始排名'] = [player['start_rank'] for player in trend_data]
            data_dict['结束排名'] = [player['end_rank'] for player in trend_data]
            data_dict['排名变化'] = [player['rank_change'] for player in trend_data]
        
        if "lv" in display_fields:
            data_dict['起始等级'] = [player['start_lv'] for player in trend_data]
            data_dict['结束等级'] = [player['end_lv'] for player in trend_data]
            data_dict['等级变化'] = [player['lv_change'] for player in trend_data]
        
        if "exp" in display_fields:
            data_dict['起始经验'] = [player['start_exp'] for player in trend_data]
            data_dict['结束经验'] = [player['end_exp'] for player in trend_data]
            data_dict['经验变化'] = [player['exp_change'] for player in trend_data]
        
        if "acc" in display_fields:
            data_dict['起始准确率'] = [player['start_acc'] for player in trend_data]
            data_dict['结束准确率'] = [player['end_acc'] for player in trend_data]
            data_dict['准确率变化'] = [player['acc_change'] for player in trend_data]
        
        if "combo" in display_fields:
            data_dict['起始连击'] = [player['start_combo'] for player in trend_data]
            data_dict['结束连击'] = [player['end_combo'] for player in trend_data]
            data_dict['连击变化'] = [player['combo_change'] for player in trend_data]
        
        if "pc" in display_fields:
            data_dict['起始游玩次数'] = [player['start_pc'] for player in trend_data]
            data_dict['结束游玩次数'] = [player['end_pc'] for player in trend_data]
            data_dict['游玩次数变化'] = [player['pc_change'] for player in trend_data]
        
        df = pd.DataFrame(data_dict)
        
        # 生成文件名
        mode_name = self.mode_names.get(mode, "未知")
        base_filename = f"trend_mode{mode}_{start_date.strftime('%Y%m%d')}_{end_point.strftime('%Y%m%d')}.csv"
        filename = self.get_unique_filename(base_filename, "csv")
        filepath = os.path.join(self.output_dir, filename)
        
        # 保存文件
        df.to_csv(filepath, index=False, encoding='utf-8-sig')
        print(colorize(f"\n已导出趋势数据: {filepath}", Colors.GREEN))
    
    @db_safe_operation
    def do_search(self, arg):
        """
        通用搜索功能（支持选择器筛选）
        
        用法: search <关键词> [类型] [模式]
        参数:
        关键词 - 要搜索的内容
        类型   - player(玩家), chart(谱面), creator(创作者), 默认为player
        模式   - 可选，模式编号
        
        示例:
        search Zani                    # 搜索玩家Zani
        search "song title" chart      # 搜索谱面
        search creator_name creator    # 搜索创作者
        search 123456 player           # 搜索UID为123456的玩家
        """
        args = arg.split()
        if not args:
            print(colorize("错误: 请输入搜索关键词", Colors.RED))
            return
        
        keyword = args[0]
        search_type = "player"
        mode = self.current_mode
        
        if len(args) > 1:
            search_type = args[1].lower()
        
        if len(args) > 2:
            try:
                mode = int(args[2])
            except ValueError:
                print(colorize("错误: 模式必须是数字", Colors.RED))
                return
        
        cursor = self.conn.cursor()
        
        if search_type == "player":
            self._search_players(cursor, keyword, mode)
        elif search_type == "chart":
            self._search_charts(cursor, keyword, mode)
        elif search_type == "creator":
            self._search_creators(cursor, keyword, mode)
        else:
            print(colorize(f"错误: 不支持的搜索类型 '{search_type}'", Colors.RED))

    def _search_players(self, cursor, keyword, mode):
        """搜索玩家（支持名称和UID）"""
        # 使用选择器构建玩家查询条件
        where_clause, params = self.selector.build_player_sql_where("pr")
        
        if keyword.isdigit():
            # UID搜索
            cursor.execute(
                f"SELECT pi.player_id, pi.current_name, pi.uid FROM player_identity pi WHERE pi.uid = ?", 
                (keyword,)
            )
            result = cursor.fetchone()
            if result:
                player_id, name, uid = result
                # 应用选择器筛选查询玩家数据
                player_where, player_params = self.selector.build_player_sql_where("pr")
                player_where += " AND pr.player_id = ?"
                player_params.append(player_id)
                
                cursor.execute(
                    f"""
                    SELECT pr.rank, pr.lv, pr.acc, pr.combo, pr.pc, pr.crawl_time
                    FROM player_rankings pr
                    WHERE {player_where}
                    ORDER BY pr.crawl_time DESC LIMIT 1
                    """,
                    player_params
                )
                player_data = cursor.fetchone()
                if player_data:
                    rank, lv, acc, combo, pc, crawl_time = player_data
                    print(colorize(f"\n玩家: {name} (UID: {uid})", Colors.CYAN))
                    print(colorize(f"筛选条件: {self.selector.get_current_selection()}", Colors.YELLOW))
                    print(get_separator())
                    print(f"排名: {rank}, 等级: {lv}, 准确率: {acc:.2f}%")
                    print(f"连击: {combo}, 游玩次数: {pc}")
                    return
            
            print(colorize(f"未找到UID为 {keyword} 的玩家", Colors.YELLOW))
        else:
            # 名称搜索 - 应用选择器筛选
            where_clause += " AND pr.name LIKE ?"
            params.append(f'%{keyword}%')
            
            cursor.execute(
                f"""
                SELECT DISTINCT pr.name, pr.rank, pr.lv, pr.acc, pr.crawl_time
                FROM player_rankings pr
                WHERE {where_clause}
                ORDER BY pr.rank LIMIT 10
                """,
                params
            )
            results = cursor.fetchall()
            if results:
                print(colorize(f"\n找到 {len(results)} 个匹配玩家:", Colors.CYAN))
                print(colorize(f"筛选条件: {self.selector.get_current_selection()}", Colors.YELLOW))
                print(get_separator())
                for name, rank, lv, acc, crawl_time in results:
                    print(f"{name}: 排名 {rank}, 等级 {lv}, 准确率 {acc:.2f}%")
            else:
                print(colorize(f"未找到包含 '{keyword}' 的玩家", Colors.YELLOW))

    def _search_charts(self, cursor, keyword, mode):
        """搜索谱面"""
        # 使用选择器构建谱面查询条件
        where_clause, params = self.selector.build_chart_sql_where("c")
        where_clause += " AND (s.title LIKE ? OR s.artist LIKE ?)"
        params.extend([f'%{keyword}%', f'%{keyword}%'])
        
        cursor.execute(
            f"""
            SELECT c.cid, c.version, c.level, c.status, s.title, s.artist,
                c.creator_name, c.heat, c.donate_count, c.last_updated
            FROM charts c
            JOIN songs s ON c.sid = s.sid
            WHERE {where_clause}
            ORDER BY c.heat DESC LIMIT 10
            """,
            params
        )
        results = cursor.fetchall()
        if results:
            print(colorize(f"\n找到 {len(results)} 个匹配谱面:", Colors.CYAN))
            print(colorize(f"筛选条件: {self.selector.get_current_selection()}", Colors.YELLOW))
            print(get_separator())
            for cid, version, level, status, title, artist, creator, heat, donate, updated in results:
                status_name = {0: "Alpha", 1: "Beta", 2: "Stable"}.get(status, "Unknown")
                print(f"  {title} - {artist} (Lv.{level})")
                print(f"    版本: {version}, 状态: {status_name}, 热度: {heat}")
                print(f"    创作者: {creator}, CID: {cid}")
        else:
            print(colorize(f"未找到包含 '{keyword}' 的谱面", Colors.YELLOW))

    def _search_creators(self, cursor, keyword, mode):
        """搜索创作者"""
        # 使用选择器构建谱面查询条件
        where_clause, params = self.selector.build_chart_sql_where("c")
        where_clause += " AND c.creator_name LIKE ?"
        params.append(f'%{keyword}%')
        
        cursor.execute(
            f"""
            SELECT c.creator_name, COUNT(*) as chart_count, 
                AVG(c.heat) as avg_heat, MAX(c.heat) as max_heat
            FROM charts c
            WHERE {where_clause}
            GROUP BY c.creator_name
            ORDER BY chart_count DESC LIMIT 10
            """,
            params
        )
        results = cursor.fetchall()
        if results:
            print(colorize(f"\n找到 {len(results)} 个匹配创作者:", Colors.CYAN))
            print(colorize(f"筛选条件: {self.selector.get_current_selection()}", Colors.YELLOW))
            print(get_separator())
            for creator, count, avg_heat, max_heat in results:
                print(f"  {creator}: {count} 个谱面")
                print(f"    平均热度: {avg_heat:.1f}, 最高热度: {max_heat}")
        else:
            print(colorize(f"未找到包含 '{keyword}' 的创作者", Colors.YELLOW))

    @db_safe_operation
    def do_stb_stats(self, arg):
        """
        谱面基础统计（支持选择器筛选）
        
        用法: stb_stats [模式]
        参数:
        模式 - 可选，模式编号，默认为当前模式
        
        示例:
        stb_stats      # 当前模式统计
        stb_stats 0    # 模式0统计
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
        
        # 如果选择器中没有指定模式，且当前模式不是所有模式，使用当前模式
        if not self.selector.filters['modes'] and self.selector.current_mode != -1:
            where_clause += " AND c.mode = ?" if where_clause != "1=1" else "c.mode = ?"
            params.append(mode)
        
        stats = self._get_chart_stats(cursor, where_clause, params)
        
        # 显示模式信息
        if self.selector.filters['modes']:
            mode_str = ", ".join([f"{m}({self.mode_names.get(m, '未知')})" for m in self.selector.filters['modes']])
        elif self.selector.current_mode != -1:
            mode_str = f"{self.selector.current_mode}({self.mode_names.get(self.selector.current_mode, '未知')})"
        else:
            mode_str = "所有模式"
        
        self._display_chart_stats(stats, mode_str)

    def _get_chart_stats(self, cursor, where_clause, params):
        """获取谱面统计信息"""
        stats = {}
        
        try:
            # 总谱面数
            cursor.execute(f"SELECT COUNT(*) FROM charts c WHERE {where_clause}", params)
            stats['total_charts'] = cursor.fetchone()[0] or 0
            
            # 按状态统计
            cursor.execute(
                f"SELECT c.status, COUNT(*) FROM charts c WHERE {where_clause} GROUP BY c.status",
                params
            )
            status_results = cursor.fetchall()
            
            # 确保所有状态都显示，即使数量为0
            stats['status_dist'] = {0: 0, 1: 0, 2: 0}
            for status, count in status_results:
                if status in [0, 1, 2]:
                    stats['status_dist'][status] = count
            
            # 难度统计
            cursor.execute(
                f"SELECT c.level, COUNT(*) FROM charts c WHERE {where_clause} AND c.level IS NOT NULL AND c.level != '' GROUP BY c.level ORDER BY CAST(c.level AS REAL)",
                params
            )
            stats['level_dist'] = dict(cursor.fetchall())
            
            # 创作者统计
            cursor.execute(
                f"SELECT c.creator_name, COUNT(*) FROM charts c WHERE {where_clause} AND c.creator_name IS NOT NULL GROUP BY c.creator_name ORDER BY COUNT(*) DESC LIMIT 10",
                params
            )
            stats['top_creators'] = cursor.fetchall()
            
            # 热度统计
            cursor.execute(
                f"SELECT AVG(c.heat), MAX(c.heat), AVG(c.donate_count), MAX(c.donate_count) FROM charts c WHERE {where_clause}",
                params
            )
            heat_stats = cursor.fetchone()
            stats['heat_avg'], stats['heat_max'], stats['donate_avg'], stats['donate_max'] = heat_stats or (0, 0, 0, 0)
            
        except Exception as e:
            print(colorize(f"获取统计信息时出错: {e}", Colors.RED))
            # 返回空的统计字典
            stats = {
                'total_charts': 0,
                'status_dist': {0: 0, 1: 0, 2: 0},
                'level_dist': {},
                'top_creators': [],
                'heat_avg': 0,
                'heat_max': 0,
                'donate_avg': 0,
                'donate_max': 0
            }
        
        return stats

    def _display_chart_stats(self, stats, mode_str):
        """显示谱面统计信息"""
        print(colorize(f"\n谱面统计 - 模式 {mode_str}", Colors.CYAN))
        print(colorize(f"筛选条件: {self.selector.get_current_selection()}", Colors.YELLOW))
        print(get_separator())
        
        if not stats or stats['total_charts'] == 0:
            print(colorize("没有找到符合条件的谱面", Colors.YELLOW))
            return
        
        print(f"总谱面数: {colorize(stats['total_charts'], Colors.GREEN)}")
        
        # 状态分布 - 确保显示所有状态
        if stats['status_dist']:
            print(f"\n{colorize('状态分布:', Colors.BOLD)}")
            status_names = {0: "Alpha", 1: "Beta", 2: "Stable"}
            for status in [0, 1, 2]:  # 确保按顺序显示所有状态
                count = stats['status_dist'].get(status, 0)
                status_name = status_names.get(status, f"未知({status})")
                print(f"  {status_name}: {count}")
        
        # 难度分布
        if stats['level_dist']:
            print(f"\n{colorize('难度分布:', Colors.BOLD)}")
            for level, count in sorted(stats['level_dist'].items(), key=lambda x: float(x[0])):
                print(f"  Lv.{level}: {count}")
        
        # 热门创作者
        if stats['top_creators']:
            print(f"\n{colorize('热门创作者:', Colors.BOLD)}")
            for creator, count in stats['top_creators']:
                print(f"  {creator}: {count} 个谱面")
        
        # 热度统计
        print(f"\n{colorize('热度统计:', Colors.BOLD)}")
        print(f"  平均热度: {stats['heat_avg']:.1f}")
        print(f"  最高热度: {stats['heat_max']}")
        print(f"  平均打赏: {stats['donate_avg']:.1f}")
        print(f"  最多打赏: {stats['donate_max']}")

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

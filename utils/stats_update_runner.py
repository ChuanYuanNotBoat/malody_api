import os
import re
import shlex
import subprocess
from typing import Callable, Dict, List, Optional


ColorizeFn = Callable[[str, str], str]

PLAYER_ALLOWED_FLAGS = {
    "--uid",
    "--uid-list",
    "--uid-range",
    "--uid-file",
    "--from-db",
    "--from-leaderboard",
    "--leaderboard-mode",
    "--limit",
    "--days-since-update",
    "--max-workers",
    "--rpm",
    "--test",
    "--print-only",
    "--status",
    "--log-level",
    "--log-file",
    "--no-default-players",
    "--resume-file",
    "--save-interval",
    "--once",
}

STB_ALLOWED_FLAGS = {
    "--once",
    "--limit",
    "--rpm",
    "--source",
    "--cid-crawl",
    "--sid-crawl",
    "--retry-failed",
    "--start",
    "--end",
    "--resume",
    "--no-resume",
    "--max-retries",
    "--skip-test",
    "--log-level",
    "--log-file",
}


def split_cli_args(text: str, colorize: ColorizeFn, red: str) -> Optional[List[str]]:
    try:
        return shlex.split(text) if text else []
    except ValueError as e:
        print(colorize(f"参数解析失败: {e}", red))
        return None


def parse_cli_options(tokens: List[str], colorize: ColorizeFn, red: str) -> Optional[Dict[str, object]]:
    options: Dict[str, object] = {}
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if not token.startswith("--"):
            print(colorize(f"无效参数: {token}", red))
            return None
        if i + 1 < len(tokens) and not tokens[i + 1].startswith("--"):
            options[token] = tokens[i + 1]
            i += 2
        else:
            options[token] = True
            i += 1
    return options


def parse_positive_int(name: str, value: str, colorize: ColorizeFn, red: str) -> Optional[int]:
    try:
        iv = int(value)
        if iv <= 0:
            raise ValueError()
        return iv
    except Exception:
        print(colorize(f"参数 {name} 必须是正整数: {value}", red))
        return None


def build_update_command(
    tokens: List[str],
    base_dir: str,
    python_executable: str,
    colorize: ColorizeFn,
    red: str,
    yellow: str,
) -> Optional[List[str]]:
    crawler_flags = ["--leaderboard", "--player", "--stb"]
    selected = [f for f in crawler_flags if f in tokens]
    if len(selected) > 1:
        print(colorize("错误: --leaderboard/--player/--stb 只能选一个", red))
        return None
    crawler_type = selected[0] if selected else "--leaderboard"
    filtered_tokens = [t for t in tokens if t not in crawler_flags]
    options = parse_cli_options(filtered_tokens, colorize, red)
    if options is None:
        return None

    if crawler_type == "--leaderboard":
        script = os.path.join(base_dir, "malody_rankings.py")
        cmd = [python_executable, script]
        allow = {"--once"}
        unknown = [k for k in options.keys() if k not in allow]
        if unknown:
            print(colorize(f"leaderboard 不支持参数: {', '.join(unknown)}", red))
            return None
        if options.get("--once") is True or not tokens:
            cmd.append("--once")
        return cmd

    if crawler_type == "--player":
        script = os.path.join(base_dir, "player_profile_crawler.py")
        cmd = [python_executable, script]
        unknown = [k for k in options.keys() if k not in PLAYER_ALLOWED_FLAGS]
        if unknown:
            print(colorize(f"player 不支持参数: {', '.join(unknown)}", red))
            return None

        if options.get("--once"):
            print(colorize("提示: player_profile_crawler.py 不支持 --once，已忽略", yellow))

        value_flags = ["--uid", "--uid-list", "--uid-range", "--uid-file", "--log-level", "--log-file", "--resume-file"]
        int_flags = ["--leaderboard-mode", "--limit", "--days-since-update", "--max-workers", "--rpm", "--save-interval"]
        bool_flags = ["--from-db", "--from-leaderboard", "--test", "--print-only", "--status", "--no-default-players"]

        for f in value_flags:
            v = options.get(f)
            if isinstance(v, str):
                cmd.extend([f, v])

        for f in int_flags:
            v = options.get(f)
            if isinstance(v, str):
                iv = parse_positive_int(f, v, colorize, red)
                if iv is None:
                    return None
                cmd.extend([f, str(iv)])

        for f in bool_flags:
            if options.get(f) is True:
                cmd.append(f)
        return cmd

    script = os.path.join(base_dir, "stb_crawler.py")
    cmd = [python_executable, script]
    unknown = [k for k in options.keys() if k not in STB_ALLOWED_FLAGS]
    if unknown:
        print(colorize(f"stb 不支持参数: {', '.join(unknown)}", red))
        return None

    if options.get("--once") is True:
        cmd.append("--once")
    if options.get("--skip-test") is True:
        cmd.append("--skip-test")

    if isinstance(options.get("--source"), str):
        source = options["--source"]
        if source not in ["all", "home", "latest", "api"]:
            print(colorize("--source 仅支持 all/home/latest/api", red))
            return None
        cmd.extend(["--source", source])

    if isinstance(options.get("--limit"), str):
        iv = parse_positive_int("--limit", options["--limit"], colorize, red)
        if iv is None:
            return None
        cmd.extend(["--max-charts", str(iv)])

    if isinstance(options.get("--rpm"), str):
        iv = parse_positive_int("--rpm", options["--rpm"], colorize, red)
        if iv is None:
            return None
        cmd.extend(["--rpm", str(iv)])

    if isinstance(options.get("--max-retries"), str):
        iv = parse_positive_int("--max-retries", options["--max-retries"], colorize, red)
        if iv is None:
            return None
        cmd.extend(["--max-retries", str(iv)])

    cid_crawl = options.get("--cid-crawl") is True
    sid_crawl = options.get("--sid-crawl") is True
    retry_failed = options.get("--retry-failed") is True
    if cid_crawl:
        cmd.append("--cid-crawl")
    if sid_crawl:
        cmd.append("--sid-crawl")
    if retry_failed:
        cmd.append("--retry-failed")

    start_value = options.get("--start")
    end_value = options.get("--end")
    if isinstance(start_value, str):
        sv = parse_positive_int("--start", start_value, colorize, red)
        if sv is None:
            return None
        if cid_crawl or (not sid_crawl):
            cmd.extend(["--start-cid", str(sv)])
        if sid_crawl:
            cmd.extend(["--start-sid", str(sv)])
    if isinstance(end_value, str):
        ev = parse_positive_int("--end", end_value, colorize, red)
        if ev is None:
            return None
        if cid_crawl or (not sid_crawl):
            cmd.extend(["--end-cid", str(ev)])
        if sid_crawl:
            cmd.extend(["--end-sid", str(ev)])

    if "--no-resume" in options:
        cmd.append("--no-resume")
    elif isinstance(options.get("--resume"), str):
        rv = options["--resume"].strip().lower()
        if rv in ["false", "0", "no", "n"]:
            cmd.append("--no-resume")
        elif rv not in ["true", "1", "yes", "y"]:
            print(colorize("--resume 仅支持 true/false", red))
            return None

    if isinstance(options.get("--log-level"), str):
        level = str(options["--log-level"]).upper()
        if level not in ["DEBUG", "INFO", "WARNING", "ERROR"]:
            print(colorize("--log-level 仅支持 DEBUG/INFO/WARNING/ERROR", red))
            return None
        cmd.extend(["--log-level", level])
    if isinstance(options.get("--log-file"), str):
        cmd.extend(["--log-file", options["--log-file"]])
    return cmd


def run_streaming_command(cmd: List[str], colorize: ColorizeFn, cyan: str, green: str, red: str) -> None:
    print(colorize(f"\n开始执行: {' '.join(cmd)}", cyan))
    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            bufsize=1,
        )
        for line in process.stdout:
            clean_line = re.sub(r"\x1b\[[0-9;]*[mK]", "", line.strip())
            if clean_line:
                print(clean_line)
        process.wait()
        if process.returncode == 0:
            print(colorize("\n数据更新成功!", green))
        else:
            print(colorize(f"\n数据更新失败，退出码: {process.returncode}", red))
    except Exception as e:
        print(colorize(f"\n更新过程中发生错误: {e}", red))

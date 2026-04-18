import json
import os


def install(cls, *, colorize, colors, get_separator):
    def do_crawl_status(self, arg):
        """
        查看各爬虫的进度状态
        """
        print(colorize("\n爬虫进度状态", colors.CYAN))
        print(get_separator())

        cid_progress = "cid_progress.json"
        if os.path.exists(cid_progress):
            try:
                with open(cid_progress, "r", encoding="utf-8") as f:
                    data = json.load(f)
                current = data.get("current_cid", "N/A")
                success = data.get("total_success", 0)
                errors = data.get("total_errors", 0)
                retry = len(data.get("retry_queue", []))
                print(f"CID爬虫: 当前CID={current}, 成功={success}, 错误={errors}, 待重试={retry}")
            except Exception:
                print("CID爬虫: 无法解析进度文件")
        else:
            print("CID爬虫: 无进度文件")

        sid_progress = "sid_progress.json"
        if os.path.exists(sid_progress):
            try:
                with open(sid_progress, "r", encoding="utf-8") as f:
                    data = json.load(f)
                current = data.get("current_sid", "N/A")
                songs = data.get("total_songs", 0)
                charts = data.get("total_charts", 0)
                empty = len(data.get("empty_songs", []))
                print(f"SID爬虫: 当前SID={current}, 歌曲={songs}, 谱面={charts}, 空歌曲={empty}")
            except Exception:
                print("SID爬虫: 无法解析进度文件")
        else:
            print("SID爬虫: 无进度文件")

        sid_back = "sid_backwards_progress.json"
        if os.path.exists(sid_back):
            try:
                with open(sid_back, "r", encoding="utf-8") as f:
                    data = json.load(f)
                current = data.get("current_sid", "N/A")
                last_valid = data.get("last_valid_sid", "N/A")
                songs = data.get("total_songs", 0)
                charts = data.get("total_charts", 0)
                print(f"向后SID爬虫: 当前SID={current}, 最后有效={last_valid}, 歌曲={songs}, 谱面={charts}")
            except Exception:
                print("向后SID爬虫: 无法解析进度文件")
        else:
            print("向后SID爬虫: 无进度文件")

        global_prog = "global_progress.bin"
        if os.path.exists(global_prog):
            size = os.path.getsize(global_prog)
            print(f"全局进度文件: 存在 ({size} bytes)")
        else:
            print("全局进度文件: 不存在")

    setattr(cls, "do_crawl_status", do_crawl_status)


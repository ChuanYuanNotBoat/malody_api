import os


def install(cls, *, colorize, colors, get_separator, db_safe_operation):
    def do_ls(self, arg):
        """
        列出当前目录的文件和目录
        """
        path = arg if arg else "."
        try:
            if os.path.exists(path):
                items = os.listdir(path)
                print(colorize(f"\n{path} 目录内容:", colors.CYAN))
                print(get_separator())
                for item in items:
                    full_path = os.path.join(path, item)
                    if os.path.isdir(full_path):
                        print(colorize(f"[目录] {item}/", colors.BLUE))
                    else:
                        size = os.path.getsize(full_path)
                        print(f"[文件] {item} ({size} 字节)")
            else:
                print(colorize(f"路径不存在: {path}", colors.RED))
        except Exception as e:
            print(colorize(f"列出目录时出错: {e}", colors.RED))

    def do_mode(self, arg):
        """
        设置或查看当前模式（支持 * 表示所有模式）
        """
        if not arg:
            mode_name = self.mode_names.get(self.current_mode, "未知")
            print(colorize(f"\n当前模式: {self.current_mode} ({mode_name})", colors.CYAN))
            print(colorize(f"当前筛选: {self.selector.get_current_selection()}", colors.YELLOW))
            return

        if arg == "*":
            self.current_mode = -1
            self.selector.current_mode = -1
            self.selector.set_filters(modes=[])
            print(colorize("\n已切换到所有模式", colors.GREEN))
            return

        try:
            mode = int(arg)
            if mode not in self.mode_names or mode == -1:
                print(colorize("错误: 模式必须在 0-9 之间，或使用 * 表示所有模式", colors.RED))
                return
            self.current_mode = mode
            self.selector.current_mode = mode
            self.selector.set_filters(modes=[mode])
            mode_name = self.mode_names.get(mode, "未知")
            print(colorize(f"\n已切换到模式: {mode} ({mode_name})", colors.GREEN))
        except ValueError:
            print(colorize("错误: 请输入有效的模式数字(0-9)或 *", colors.RED))

    def do_exit(self, arg):
        """退出程序"""
        print(colorize("\n感谢使用 Malody 排行榜数据可视化工具!", colors.CYAN))
        self.cleanup()
        return True

    def do_quit(self, arg):
        """退出程序"""
        return self.do_exit(arg)

    setattr(cls, "do_ls", db_safe_operation(do_ls))
    setattr(cls, "do_mode", do_mode)
    setattr(cls, "do_exit", do_exit)
    setattr(cls, "do_quit", do_quit)
    setattr(cls, "do_q", do_quit)
    setattr(cls, "do_e", do_exit)


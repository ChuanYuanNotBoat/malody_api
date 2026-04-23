def install(cls, *, colorize, colors, get_separator):
    Colors = colors
    def do_select(self, arg):
        """
        设置筛选条件（类似MC选择器）
        
        用法: select <选择器>
        选择器格式:
        @p[玩家1,玩家2,...]    - 选择玩家（支持名称或UID）
        @d[难度范围]          - 选择难度（如 5, 5-10）
        @t[时间范围]          - 选择时间（如 7d, 30d, 2024-01-01）
        @m[模式列表]          - 选择模式（如 0,3,5）
        @s[状态列表]          - 选择状态（如 0,2 - 0=Alpha,1=Beta,2=Stable）
        @*                   - 选择所有（清除筛选）
        
        示例:
        select @p[Zani]              # 选择玩家Zani
        select @d[5-10]              # 选择难度5-10
        select @t[7d]                # 选择最近7天
        select @m[0,3]               # 选择模式0和3
        select @s[2]                 # 选择状态为Stable的谱面
        select @p[Zani] @d[5-10]     # 组合筛选
        select @*                    # 清除所有筛选
        """
        if not arg:
            print(colorize("\n当前筛选条件:", Colors.CYAN))
            print(get_separator())
            print(self.selector.get_current_selection())
            return
        
        if arg.strip() == "@*":
            self.selector.clear_filters()
            print(colorize("已清除所有筛选条件", Colors.GREEN))
            return
        
        # 解析选择器
        filters = self.selector.parse_selector(arg)
        
        # 应用筛选条件
        if 'players' in filters:
            self.selector.set_filters(players=filters['players'])
        if 'difficulties' in filters:
            self.selector.set_filters(difficulties=filters['difficulties'])
        if 'time_range' in filters:
            self.selector.set_filters(time_range=filters['time_range'])
        if 'modes' in filters:
            self.selector.set_filters(modes=filters['modes'])
            # 如果选择了具体模式，更新当前模式为第一个模式
            if filters['modes']:
                self.current_mode = filters['modes'][0]
        if 'statuses' in filters:
            self.selector.set_filters(statuses=filters['statuses'])
        
        print(colorize("\n已应用筛选条件:", Colors.GREEN))
        print(get_separator())
        print(self.selector.get_current_selection())


    setattr(cls, "do_select", do_select)


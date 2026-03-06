import io
import inspect
import pandas as pd
from nicegui import ui

# --- 注入硬编码 CSS，防止动态颜色被清除 ---
ui.add_css('''
    .row-pass { background-color: #dcfce7 !important; color: #166534 !important; font-weight: 500; }
    .row-fail { background-color: #fee2e2 !important; color: #991b1b !important; }
''')

# --- 全局状态管理 ---
app_state = {
    'namelist': None,
    'yonma': None,
    'sanma': None
}

result_store = {'yonma': None, 'sanma': None}
warning_store = {'yonma': [], 'sanma': []}


# --- 核心数据处理逻辑 ---
def process_data(df_matches, df_namelist, mode="yonma"):
    num_players = 4 if mode == "yonma" else 3

    name_cols = [3, 6, 9, 12][:num_players]
    score_cols = [5, 8, 11, 14][:num_players]

    if df_namelist.empty or len(df_namelist.columns) == 0:
        namelist_lower = []
    else:
        namelist_lower = [str(x).lower().strip() for x in df_namelist.iloc[:, 0].dropna().tolist()]

    valid_matches = []
    unregistered_players = set()  # 用集合来记录发现的未报名选手，自动去重

    # 1. 遍历所有对局（不再因为未报名选手而剔除整局）
    for idx, row in df_matches.iterrows():
        try:
            match_players = [str(row.iloc[c]).strip() for c in name_cols]
            match_scores = [float(row.iloc[c]) for c in score_cols]
        except (IndexError, ValueError):
            continue

        valid_matches.append((match_players, match_scores))

        # 检查并记录未报名选手（仅用于 UI 提示）
        for p in match_players:
            p_lower = p.lower()
            is_valid = any(valid_name in p_lower for valid_name in namelist_lower)
            if not is_valid:
                unregistered_players.add(p)

    # 2. 生成选手成绩 Map (所有人都参与成绩统计)
    player_scores = {}
    for players, scores in valid_matches:
        for p, s in zip(players, scores):
            if p not in player_scores:
                player_scores[p] = []
            player_scores[p].append(s)

    # 3. 计算最终成绩并过滤输出
    results = []
    for p, scores in player_scores.items():
        # 【核心改动】：如果该选手不在白名单内，直接跳过，不输出到最终名单
        p_lower = p.lower()
        is_valid = any(valid_name in p_lower for valid_name in namelist_lower)
        if not is_valid:
            continue

        scores_reversed = scores[::-1]
        n = len(scores_reversed)

        if n >= 5:
            max_avg = -99999.99
            for i in range(5, min(20, n) + 1):
                avg = sum(scores_reversed[:i]) / i
                if avg > max_avg:
                    max_avg = avg
            final_score = max_avg
        else:
            final_score = "对局场次不足"

        row_dict = {"最终成绩": final_score, "用户名": p}
        for i, s in enumerate(scores_reversed):
            row_dict[f"第{i + 1}场"] = s
        results.append(row_dict)

    df_res = pd.DataFrame(results)

    # 4. 排序与格式整理
    if df_res.empty:
        df_res = pd.DataFrame(columns=["最终成绩", "用户名", "第1场"])
    else:
        valid_mask = df_res["最终成绩"] != "对局场次不足"
        df_valid = df_res[valid_mask].copy()
        df_invalid = df_res[~valid_mask].copy()

        df_valid["最终成绩"] = df_valid["最终成绩"].astype(float)
        df_valid = df_valid.sort_values(by="最终成绩", ascending=False)

        df_res = pd.concat([df_valid, df_invalid], ignore_index=True)
        base_cols = ["最终成绩", "用户名"]
        game_cols = [c for c in df_res.columns if c not in base_cols]
        game_cols.sort(key=lambda x: int(x.replace("第", "").replace("场", "")))
        df_res = df_res[base_cols + game_cols]

    return df_res, list(unregistered_players)


# --- UI 交互逻辑 ---
async def handle_upload(e, key):
    try:
        file_name = e.file.name if hasattr(e, 'file') else e.name
        file_obj = e.file if hasattr(e, 'file') else e.content

        content = file_obj.read()
        if inspect.iscoroutine(content):
            content = await content

        if not file_name.endswith('.csv'):
            ui.notify(f"目前仅支持 CSV 格式: {file_name}", type='negative')
            return

        df = None
        for enc in ['utf-8', 'utf-8-sig', 'gbk', 'gb18030']:
            try:
                if key == 'namelist':
                    df = pd.read_csv(io.BytesIO(content), encoding=enc, header=None)
                else:
                    df = pd.read_csv(io.BytesIO(content), encoding=enc)
                break
            except UnicodeDecodeError:
                continue

        if df is None:
            ui.notify(f"{file_name} 编码无法识别，请确保是普通的 CSV 文件。", type='negative')
            return

        app_state[key] = df
        ui.notify(f"成功导入: {file_name}", type='positive')

    except Exception as ex:
        ui.notify(f"文件读取失败: {str(ex)}", type='negative')


def calculate_and_refresh(mode, silent=False):
    if app_state['namelist'] is None:
        if not silent: ui.notify("请先上传 白名单 (Namelist) 的 CSV！", type='warning')
        return
    if app_state[mode] is None:
        name = "四人" if mode == 'yonma' else "三人"
        if not silent: ui.notify(f"请先上传 {name}麻将 牌谱 CSV！", type='warning')
        return

    df_res, warnings = process_data(app_state[mode], app_state['namelist'], mode)
    result_store[mode] = df_res
    warning_store[mode] = warnings

    if not silent:
        if df_res.empty or len(df_res.dropna(how='all')) == 0:
            ui.notify(f"计算完成，但所有有效选手对局数为 0！", type='negative')
        else:
            ui.notify(f"计算完成！共生成 {len(df_res)} 名有效选手的成绩。", type='positive')

    result_ui.refresh(mode)


def silent_calculate_and_refresh(mode):
    calculate_and_refresh(mode, silent=True)


def on_tab_change(e):
    mode = 'sanma' if e.value == 'sanma' else 'yonma'
    if app_state['namelist'] is not None and app_state[mode] is not None:
        silent_calculate_and_refresh(mode)


def download_result(mode):
    df = result_store[mode]
    if df is not None:
        output = io.BytesIO()
        df.to_csv(output, index=False, encoding='utf-8-sig')
        output.seek(0)
        file_name = f"{'四人' if mode == 'yonma' else '三人'}麻将成绩表.csv"
        ui.download(output.read(), filename=file_name)


# --- 构建界面 ---
ui.page_title('雀魂赛事成绩统计器')


async def upload_namelist(e): await handle_upload(e, 'namelist')


async def upload_yonma(e): await handle_upload(e, 'yonma')


async def upload_sanma(e): await handle_upload(e, 'sanma')


with ui.column().classes('w-full items-center p-4'):
    ui.label('🀄 雀魂赛事牌谱成绩计算工具').classes('text-3xl font-bold mb-6 text-primary')

    with ui.row().classes('w-full max-w-5xl gap-6 justify-center'):
        with ui.card().classes('w-72 items-center text-center'):
            ui.label("1. 导入白名单").classes('font-bold text-lg')
            ui.upload(on_upload=upload_namelist, auto_upload=True).classes('w-full')
            ui.label("仅支持 .csv").classes('text-red-500 font-bold text-sm')

        with ui.card().classes('w-72 items-center text-center'):
            ui.label("2. 导入四人麻将牌谱").classes('font-bold text-lg')
            ui.upload(on_upload=upload_yonma, auto_upload=True).classes('w-full')
            ui.label("仅支持 .csv").classes('text-gray-400 text-sm')

        with ui.card().classes('w-72 items-center text-center'):
            ui.label("3. 导入三人麻将牌谱").classes('font-bold text-lg')
            ui.upload(on_upload=upload_sanma, auto_upload=True).classes('w-full')
            ui.label("仅支持 .csv").classes('text-gray-400 text-sm')

    ui.separator().classes('w-full max-w-5xl my-6')


    @ui.refreshable
    def result_ui(mode):
        df = result_store.get(mode)
        warnings = warning_store.get(mode, [])

        # 【核心改动】：重写警告面板，现在仅展示被隐藏的未报名玩家名单
        if warnings:
            with ui.expansion(f"⚠️ 发现 {len(warnings)} 名未报名选手（对局已正常计算，最终名单已隐藏其成绩）",
                              icon='warning').classes('w-full bg-yellow-50 text-yellow-800 font-bold mb-4'):
                with ui.row().classes('gap-2 p-3 w-full flex-wrap'):
                    for p in warnings:
                        ui.label(p).classes('text-yellow-800 font-bold bg-yellow-200 px-2 py-0.5 rounded')
        elif df is not None:
            ui.label("✅ 所有参赛选手均已报名。").classes('text-green-600 font-bold mb-4')

        if df is not None:
            with ui.row().classes('w-full justify-between items-end mb-2'):
                ui.label("💡 提示: 表格仅展示总分，下载的 CSV 中包含各局明细").classes('text-gray-500 text-sm')
                ui.button("⬇️ 下载成绩表 (.CSV)", on_click=lambda: download_result(mode)).classes(
                    'bg-blue-500 text-white')

            if not df.empty and "最终成绩" in df.columns and "用户名" in df.columns:
                display_df = df[["最终成绩", "用户名"]].copy()
                display_df = display_df.reset_index(drop=True)

                limit = 16 if mode == 'yonma' else 9

                def determine_class(row):
                    if str(row['最终成绩']) == '对局场次不足':
                        return 'row-fail'
                    elif row.name < limit:
                        return 'row-pass'
                    else:
                        return 'row-fail'

                display_df['row_class'] = display_df.apply(determine_class, axis=1)
                display_df.insert(0, 'rank', range(1, len(display_df) + 1))

                display_df.rename(columns={"最终成绩": "score", "用户名": "username"}, inplace=True)
                display_df = display_df.fillna("").astype(str)

            else:
                display_df = pd.DataFrame(columns=["rank", "score", "username", "row_class"])

            aggrid_options = {
                'columnDefs': [
                    {'headerName': '排名', 'field': 'rank', 'width': 80},
                    {'headerName': '最终成绩', 'field': 'score'},
                    {'headerName': '用户名', 'field': 'username'}
                ],
                'rowData': display_df.to_dict('records'),
                'rowClassRules': {
                    'row-pass': 'data && data.row_class === "row-pass"',
                    'row-fail': 'data && data.row_class === "row-fail"'
                },
                'defaultColDef': {'minWidth': 120},
                'overlayNoRowsTemplate': '<span class="text-gray-400">没有符合条件的有效选手数据</span>',
            }

            ui.aggrid(aggrid_options).classes('h-[500px] w-full')


    with ui.tabs(on_change=on_tab_change).classes('w-full max-w-5xl') as tabs:
        yonma_tab = ui.tab('yonma', label='四人麻将处理')
        sanma_tab = ui.tab('sanma', label='三人麻将处理')

    with ui.tab_panels(tabs, value=yonma_tab).classes('w-full max-w-5xl shadow-md rounded-lg border'):
        with ui.tab_panel('yonma'):
            ui.button("▶️ 手动计算四人成绩", on_click=lambda: calculate_and_refresh('yonma')).classes(
                'mb-4 w-full bg-blue-500 text-white font-bold')
            result_ui('yonma')

        with ui.tab_panel('sanma'):
            ui.button("▶️ 手动计算三人成绩", on_click=lambda: calculate_and_refresh('sanma')).classes(
                'mb-4 w-full bg-purple-500 text-white font-bold')
            result_ui('sanma')

ui.run(host='127.0.0.1', port=1146, title="雀魂赛事统计")
import requests
import time
import sys
from datetime import datetime
import csv
import os

# 强制 UTF-8 输出
sys.stdout.reconfigure(encoding='utf-8')

# ==========================================
# 【核心配置区】
API_KEY = ""
MY_STEAM_ID = ""
SERVERCHAN_KEY = "" # 如果你想测微信推送，去 Server酱 领个 Key 填这里

# 【实验开关】
# 设置为 True：脚本会连你自己一起监控，方便测试。
# 设置为 False：恢复正常模式，只监控好友列表。
MONITOR_MYSELF = True
# ==========================================

class SteamMonitor:
    def __init__(self, api_key, steam_id, push_key):
        self.api_key = api_key
        self.steam_id = steam_id
        self.push_key = push_key
        
        self.friends_cache = {} 
        self.achievements_cache = {} 
        self.schema_cache = {} 
        self.is_first_scan = True

    # --- 微信推送模块 ---
    def send_push(self, title, content=""):
        if not self.push_key: return 
        try:
            url = f"https://sctapi.ftqq.com/{self.push_key}.send"
            requests.post(url, data={"title": title, "desp": content}, timeout=5)
        except Exception:
            pass

    # --- CSV 本地记录模块 ---
    def log_to_csv(self, name, action, detail):
        file_exists = os.path.isfile('steam_log.csv')
        try:
            with open('steam_log.csv', mode='a', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f)
                if not file_exists:
                    writer.writerow(['时间', '好友昵称', '动作', '详情'])
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                writer.writerow([now, name, action, detail])
        except Exception:
            pass

    # --- 基础信息获取模块 ---
    def get_friend_list(self):
        url = f"http://api.steampowered.com/ISteamUser/GetFriendList/v0001/?key={self.api_key}&steamid={self.steam_id}&relationship=friend"
        try:
            res = requests.get(url, timeout=10).json()
            return [f['steamid'] for f in res.get('friendslist', {}).get('friends', [])]
        except: return []

    def get_player_summaries(self, steam_ids):
        if not steam_ids: return []
        ids_str = ",".join(steam_ids)
        url = f"http://api.steampowered.com/ISteamUser/GetPlayerSummaries/v0002/?key={self.api_key}&steamids={ids_str}"
        try:
            res = requests.get(url, timeout=10).json()
            return res.get('response', {}).get('players', [])
        except: return []

    # --- 历史总时长查询模块 ---
    def get_total_playtime(self, steam_id, app_id):
        url = f"http://api.steampowered.com/IPlayerService/GetOwnedGames/v0001/?key={self.api_key}&steamid={steam_id}&format=json"
        try:
            res = requests.get(url, timeout=10).json()
            games = res.get('response', {}).get('games', [])
            for g in games:
                if str(g.get('appid')) == str(app_id):
                    playtime_forever = g.get('playtime_forever', 0) 
                    if playtime_forever == 0: return "未知"
                    h, m = divmod(playtime_forever, 60)
                    return f"{h}小时{m}分钟"
        except: pass
        return "未知(或隐藏了动态)"

    # --- 成就翻译模块 ---
    def get_achievement_display_name(self, app_id, api_name):
        if app_id not in self.schema_cache:
            url = f"http://api.steampowered.com/ISteamUserStats/GetSchemaForGame/v2/?key={self.api_key}&appid={app_id}&l=schinese"
            try:
                res = requests.get(url, timeout=10).json()
                achievements = res.get('game', {}).get('availableGameStats', {}).get('achievements', [])
                mapping = {}
                for ach in achievements:
                    name = ach.get('displayName', ach['name'])
                    desc = ach.get('description', '')
                    mapping[ach['name']] = f"【{name}】 ({desc})" if desc else f"【{name}】"
                self.schema_cache[app_id] = mapping
            except:
                self.schema_cache[app_id] = {} 

        mapping = self.schema_cache.get(app_id, {})
        return mapping.get(api_name, f"【{api_name}】")

    def get_new_achievements(self, steam_id, app_id):
        url = f"http://api.steampowered.com/ISteamUserStats/GetPlayerAchievements/v0001/?appid={app_id}&key={self.api_key}&steamid={steam_id}"
        try:
            res = requests.get(url, timeout=10).json()
            player_stats = res.get('playerstats', {})
            
            if not player_stats.get('success') or 'achievements' not in player_stats:
                return []

            current_achievements = [a['apiname'] for a in player_stats['achievements'] if a['achieved'] == 1]
            
            if steam_id not in self.achievements_cache:
                self.achievements_cache[steam_id] = {}
            if app_id not in self.achievements_cache[steam_id]:
                self.achievements_cache[steam_id][app_id] = current_achievements
                return [] 

            old_achievements = self.achievements_cache[steam_id][app_id]
            new_unlocks = [ach for ach in current_achievements if ach not in old_achievements]
            
            self.achievements_cache[steam_id][app_id] = current_achievements
            return new_unlocks
        except: return []

    # --- 核心状态机 ---
    def process_friend(self, player):
        steam_id = player.get('steamid')
        name = player.get('personaname', '未知好友')
        
        # 加上一个特殊的标记，方便你认出哪个是自己
        if steam_id == self.steam_id:
            name = f"🌟[我自己] {name}"

        status_code = player.get('personastate', 0)
        is_online = (status_code != 0)
        
        game_id = player.get('gameid')
        game_name = player.get('gameextrainfo')
        is_in_game = (game_name is not None)
        
        now_time = datetime.now().strftime("%H:%M:%S")

        if steam_id not in self.friends_cache:
            self.friends_cache[steam_id] = {
                'is_online': is_online,
                'is_in_game': is_in_game,
                'game_name': game_name,
                'game_id': game_id,
                'start_time': time.time() if is_in_game else 0
            }
            if self.is_first_scan and is_in_game:
                print(f"[{now_time}] [扫描] {name} 正在玩 -> {game_name}")
            elif self.is_first_scan and is_online:
                print(f"[{now_time}] [扫描] {name} 当前在线")
            return

        old_data = self.friends_cache[steam_id]

        if not old_data['is_online'] and is_online:
            print(f"[{now_time}] [+] {name} 上线了")
            self.log_to_csv(name, "上线", "")
            
        elif old_data['is_online'] and not is_online:
            print(f"[{now_time}] [-] {name} 下线了")
            self.log_to_csv(name, "下线", "")

        if not old_data['is_in_game'] and is_in_game:
            msg = f"开始玩 -> {game_name}"
            print(f"[{now_time}] [🎮] {name} {msg}")
            self.friends_cache[steam_id]['start_time'] = time.time()
            self.friends_cache[steam_id]['game_id'] = game_id
            self.log_to_csv(name, "开始游戏", game_name)
            self.send_push(f"Steam动态: {name} 开玩啦", msg) 
            
        elif old_data['is_in_game'] and not is_in_game:
            start_t = old_data.get('start_time', 0)
            duration_msg = ""
            if start_t > 0:
                m, s = divmod(int(time.time() - start_t), 60)
                h, m = divmod(m, 60)
                duration_msg = f"{h}小时{m}分{s}秒" if h > 0 else f"{m}分{s}秒"

            old_game_name = old_data['game_name']
            old_game_id = old_data['game_id']
            
            total_playtime = self.get_total_playtime(steam_id, old_game_id)

            msg = f"结束游玩 {old_game_name} (本次时长: {duration_msg} | 历史总时长: {total_playtime})"
            print(f"[{now_time}] [🛑] {name} {msg}")
            self.log_to_csv(name, "结束游戏", msg)
            self.send_push(f"Steam动态: {name} 游戏结束", msg) 

        if is_in_game and game_id:
            new_achievements = self.get_new_achievements(steam_id, game_id)
            for ach in new_achievements:
                real_name = self.get_achievement_display_name(game_id, ach)
                
                msg = f"在 {game_name} 中解锁了新成就: {real_name}!"
                print(f"[{now_time}] [🏆] {name} {msg}")
                self.log_to_csv(name, "解锁成就", f"{game_name} - {real_name}")
                self.send_push(f"🏆 {name} 解锁了新成就", f"游戏: {game_name}\n成就: {real_name}") 

        new_start_time = old_data.get('start_time', 0)
        if is_in_game and not old_data['is_in_game']:
            new_start_time = time.time()

        self.friends_cache[steam_id] = {
            'is_online': is_online,
            'is_in_game': is_in_game,
            'game_name': game_name,
            'game_id': game_id,
            'start_time': new_start_time
        }

    def start(self):
        print("[*] Steam 云监控中心已启动...")
        if self.push_key: print("[*] 微信推送模块: 已开启")
        else: print("[*] 微信推送模块: 未配置 (仅本地运行)")
        
        if MONITOR_MYSELF:
            print("[*] 实验开关已开启：将同步监控你自己的动态！")
        
        while True:
            friend_ids = self.get_friend_list()
            
            # --- 把自己的 ID 强行塞进监控列表 ---
            if MONITOR_MYSELF and self.steam_id not in friend_ids:
                friend_ids.append(self.steam_id)
            # ------------------------------------

            if not friend_ids:
                print("[-] 无法获取列表，请检查网络或重试。")
                time.sleep(10)
                continue
            
            chunked_ids = [friend_ids[i:i + 100] for i in range(0, len(friend_ids), 100)]
            for chunk in chunked_ids:
                players = self.get_player_summaries(chunk)
                for player in players:
                    self.process_friend(player)

            if self.is_first_scan:
                print("-" * 65)
                print("[*] 初始状态扫描完毕，开始实时监控...")
                print("-" * 65)
                self.is_first_scan = False

            time.sleep(10)

if __name__ == "__main__":
    monitor = SteamMonitor(API_KEY, MY_STEAM_ID, SERVERCHAN_KEY)

    monitor.start()

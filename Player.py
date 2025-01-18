import os
import random
import json
import tkinter as tk
from tkinter import filedialog, messagebox
from tkinter import ttk
import vlc
import time
import threading
import logging
import sys

# 配置日志记录
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

class MediaPlayerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("媒体播放器")
        root.tk.call('tk', 'scaling', 3)  # 将缩放比例设置为 1.5 倍

        # 启用高DPI支持
        if 'win' in sys.platform.lower():
            try:
                from ctypes import windll
                windll.shcore.SetProcessDpiAwareness(1)
            except Exception:
                pass

        # 设置窗口大小和居中
        window_width = 800
        window_height = 600
        screen_width = root.winfo_screenwidth()
        screen_height = root.winfo_screenheight()
        x = (screen_width // 2) - (window_width // 2)
        y = (screen_height // 2) - (window_height // 2)
        self.root.geometry(f"{window_width}x{window_height}+{x}+{y}")
        self.root.resizable(True, True)  # 允许窗口调整大小

        # 存放 VLC MediaPlayer 对象（视频和音频）
        self.video_player = None
        self.audio_player = None

        # 初始化 VLC 实例配置
        try:
            vlc_args = [
                '--network-caching=5000',     # 增加网络缓存到5000ms
                '--file-caching=5000',        # 增加文件缓存到5000ms
                '--avcodec-hw=dxva2',         # 明确使用DXVA2硬件加速 (Windows)
                '--vout=directx',             # 使用DirectX视频输出 (Windows)
                '--no-video-title-show',      # 去除视频标题显示
                '--avcodec-threads=4',        # 使用多线程解码
                # 尽量保持原生帧率、不丢帧
                '--no-skip-frames',
                '--no-drop-late-frames',
                '--clock-jitter=0',
                '--clock-synchro=0',
                '--verbose=2',                # 日志详细级别
                '--logfile=vlc_log.txt'       # 将日志输出到文件
            ]
            self.vlc_instance = vlc.Instance(vlc_args)
            logging.debug("VLC 实例已成功初始化。")
        except Exception as e:
            logging.error(f"初始化 VLC 实例失败: {e}")
            messagebox.showerror("VLC 初始化错误", f"无法初始化 VLC: {e}")
            self.root.destroy()
            return

        # 创建顶层控制框架
        control_frame = tk.Frame(root)
        control_frame.pack(pady=10)

        # 选择文件夹按钮
        self.select_button = tk.Button(control_frame, text="选择文件夹", command=self.select_folder)
        self.select_button.grid(row=0, column=0, padx=5)

        # 随机播放按钮
        self.random_button = tk.Button(control_frame, text="随机播放", command=self.play_random, state=tk.DISABLED)
        self.random_button.grid(row=0, column=1, padx=5)

        # 暂停/播放按钮
        self.pause_button = tk.Button(control_frame, text="暂停", command=self.toggle_pause, state=tk.DISABLED)
        self.pause_button.grid(row=0, column=2, padx=5)

        # 关闭视频播放按钮
        self.close_video_button = tk.Button(control_frame, text="关闭视频播放", command=self.close_video)
        self.close_video_button.grid(row=0, column=3, padx=5)

        # 创建进度条框架
        progress_frame = tk.Frame(root)
        progress_frame.pack(pady=10, fill=tk.X, padx=20)

        # 进度条标签
        self.time_label = tk.Label(progress_frame, text="00:00:00 / 00:00:00")
        self.time_label.pack(anchor='w')

        # 进度条（使用Scale作为进度条并允许用户拖动）
        self.scale = ttk.Scale(progress_frame, from_=0, to=1000, orient=tk.HORIZONTAL)
        self.scale.pack(fill=tk.X, expand=True)
        # 绑定进度条事件
        self.scale.bind("<ButtonPress-1>", self.on_scale_press)
        self.scale.bind("<ButtonRelease-1>", self.on_scale_release)
        self.scale.bind("<B1-Motion>", self.on_scale_move)

        # 创建列表框及其滚动条
        list_frame = tk.Frame(root)
        list_frame.pack(pady=10, fill=tk.BOTH, expand=True, padx=20)

        scrollbar = tk.Scrollbar(list_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.listbox = tk.Listbox(list_frame, width=100, height=20, yscrollcommand=scrollbar.set)
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.listbox.yview)

        self.listbox.bind('<<ListboxSelect>>', self.on_select)

        # 用于存储子目录与显示名称的对应关系 [(subfolder_name, display_title), ...]
        self.subfolders_info = []

        # 用于标记是否正在拖动进度条
        self.scale_dragging = False

        # 启动定期更新进度条
        self.update_progress()

    def on_scale_press(self, event):
        self.scale_dragging = True

    def on_scale_release(self, event):
        self.scale_dragging = False
        self.on_scale_move(None)  # 执行最后一次更新

    def on_scale_move(self, event):
        # 在拖动中，才更新播放进度（以视频Player为基准）
        if self.scale_dragging and self.video_player is not None:
            total_time = self.video_player.get_length()
            if total_time > 0:
                new_progress = self.scale.get()  # 0 ~ 1000
                new_time = float(new_progress) / 1000 * total_time
                # 同步设置 视频 和 音频 的时间
                self.video_player.set_time(int(new_time))
                if self.audio_player is not None:
                    self.audio_player.set_time(int(new_time))

    def select_folder(self):
        folder_path = filedialog.askdirectory()
        if folder_path:
            self.current_folder = folder_path
            self.list_subfolders(folder_path)
            self.random_button.config(state=tk.NORMAL)

    def list_subfolders(self, folder_path):
        """
        搜索子文件夹，如果其中存在 entry.json 则读取 'title' 作为显示标题；
        否则显示文件夹名称。
        """
        try:
            subfolders = [f for f in os.listdir(folder_path) if os.path.isdir(os.path.join(folder_path, f))]
            self.listbox.delete(0, tk.END)
            self.subfolders_info.clear()

            for sub in subfolders:
                sub_path = os.path.join(folder_path, sub)

                entries233 = os.listdir(sub_path)
                # 过滤出文件夹
                folders233 = [entry for entry in entries233 if os.path.isdir(os.path.join(sub_path, entry))]

                entry_file = os.path.join(sub_path, folders233[0]+"\entry.json")
                display_title = sub  # 默认用文件夹名

                if os.path.exists(entry_file):
                    try:
                        with open(entry_file, "r", encoding="utf-8") as f:
                            data = json.load(f)
                            if isinstance(data, dict) and "title" in data:
                                display_title = data["title"]
                    except Exception as e:
                        logging.warning(f"解析 {entry_file} 出错: {e}")

                self.subfolders_info.append((sub, display_title))

            for _, display_title in self.subfolders_info:
                self.listbox.insert(tk.END, display_title)

            if not subfolders:
                messagebox.showinfo("信息", "所选文件夹中没有子文件夹。")
        except Exception as e:
            messagebox.showerror("错误", f"无法读取文件夹: {e}")
            logging.error(f"无法读取文件夹: {e}")
    


    def on_select(self, event):
        selection = event.widget.curselection()
        if selection:
            index = selection[0]
            subfolder_name, _ = self.subfolders_info[index]
            subfolder_path = os.path.join(self.current_folder, subfolder_name)
            threading.Thread(target=self.play_media_in_folder, args=(subfolder_path,), daemon=True).start()

    def play_media_in_folder(self, folder_path):
        """在指定文件夹下寻找 0.blv 或 video.m4s + audio.m4s 并播放"""
        logging.debug(f"正在播放文件夹: {folder_path}")

        # 先关闭之前的播放器（如果有）
        self.close_video()

        # 递归搜索
        video_m4s = None
        audio_m4s = None
        zero_blv = None

        for root_dir, dirs, files in os.walk(folder_path):
            if '0.blv' in files:
                zero_blv = os.path.join(root_dir, '0.blv')
                break
            if 'video.m4s' in files and 'audio.m4s' in files:
                video_m4s = os.path.join(root_dir, 'video.m4s')
                audio_m4s = os.path.join(root_dir, 'audio.m4s')
                break

        if zero_blv:
            self.play_media(zero_blv, is_blv=True)
        elif video_m4s and audio_m4s:
            self.play_video_and_audio(video_m4s, audio_m4s)
        else:
            messagebox.showinfo("信息", "该文件夹中没有可播放的媒体文件。")

    def play_media(self, media_path, is_blv=False):
        """
        单独播放单文件（0.blv 或其他单一文件）。
        在此示例中，只打开一个“视频窗口”并将其最大化。
        """
        if self.video_player is not None:
            self.video_player.stop()

        # 创建一个新窗口来嵌入视频
        self.video_window = tk.Toplevel(self.root)
        self.video_window.title("视频窗口")
        # 最大化窗口（Windows 下）
        self.video_window.state("zoomed")

        # 创建一个新的 MediaPlayer 用于视频
        self.video_player = self.vlc_instance.media_player_new()

        # 将播放画面嵌入到新窗口
        video_id = self.video_window.winfo_id()
        # Windows 下使用 set_hwnd，Linux 下用 set_xwindow
        if sys.platform.startswith('win'):
            self.video_player.set_hwnd(video_id)
        else:
            self.video_player.set_xwindow(video_id)

        # 设置媒体并播放
        media = self.vlc_instance.media_new(media_path)
        self.video_player.set_media(media)
        self.video_player.audio_set_mute(False)
        self.video_player.audio_set_volume(100)
        self.video_player.play()

        # 暂停按钮可用
        self.pause_button.config(state=tk.NORMAL, text="暂停")

    def play_video_and_audio(self, video_path, audio_path):
        """
        同时打开一个新窗口播视频，另一个新窗口播音频。
        用同一个进度条和播放按钮进行控制（简单实现）。
        """
                # 创建并初始化 "音频播放器"
        if self.audio_player is not None:
            self.audio_player.stop()

        self.audio_window = tk.Toplevel(self.root)
        self.audio_window.title("音频窗口")
        self.audio_window.state("zoomed")

        self.audio_player = self.vlc_instance.media_player_new()
        audio_id = self.audio_window.winfo_id()
        if sys.platform.startswith('win'):
            self.audio_player.set_hwnd(audio_id)
        else:
            self.audio_player.set_xwindow(audio_id)

        media_audio = self.vlc_instance.media_new(audio_path)
        self.audio_player.set_media(media_audio)
        self.audio_player.audio_set_mute(False)
        self.audio_player.audio_set_volume(100)
        # 创建并初始化 "视频播放器"
        if self.video_player is not None:
            self.video_player.stop()

        self.video_window = tk.Toplevel(self.root)
        self.video_window.title("视频窗口")
        self.video_window.state("zoomed")

        self.video_player = self.vlc_instance.media_player_new()
        video_id = self.video_window.winfo_id()
        if sys.platform.startswith('win'):
            self.video_player.set_hwnd(video_id)
        else:
            self.video_player.set_xwindow(video_id)

        media_video = self.vlc_instance.media_new(video_path)
        self.video_player.set_media(media_video)
        self.video_player.audio_set_mute(False)
        self.video_player.audio_set_volume(100)

        # 开始播放
        self.video_player.play()
        self.audio_player.play()

        # 启用暂停按钮
        self.pause_button.config(state=tk.NORMAL, text="暂停")

    def play_random(self):
        """随机选择一个子目录播放"""
        if not hasattr(self, 'current_folder'):
            messagebox.showinfo("信息", "请先选择一个文件夹。")
            return
        if self.listbox.size() == 0:
            messagebox.showinfo("信息", "播放列表为空。")
            return

        random_index = random.randint(0, self.listbox.size() - 1)
        subfolder_name, _ = self.subfolders_info[random_index]
        subfolder_path = os.path.join(self.current_folder, subfolder_name)

        # 更新选中状态
        self.listbox.selection_clear(0, tk.END)
        self.listbox.selection_set(random_index)
        self.listbox.activate(random_index)

        threading.Thread(target=self.play_media_in_folder, args=(subfolder_path,), daemon=True).start()

    def toggle_pause(self):
        """同时暂停/播放 视频 和 音频"""
        # 如果都空，则直接返回
        if self.video_player is None and self.audio_player is None:
            return

        # 如果视频播放器在播放，则统一暂停，否则统一播放
        if self.video_player is not None and self.video_player.is_playing():
            self.video_player.pause()
            if self.audio_player is not None:
                self.audio_player.pause()
            self.pause_button.config(text="播放")
        else:
            if self.video_player is not None:
                self.video_player.play()
            if self.audio_player is not None:
                self.audio_player.play()
            self.pause_button.config(text="暂停")

    def update_progress(self):
        """
        定期更新进度条和时间标签，完全以“视频播放器”为基准。
        音频播放器仅做同步，但这里演示的是简单同步。
        """
        try:
            if self.video_player is not None and self.video_player.is_playing() and not self.scale_dragging:
                current_time = self.video_player.get_time()  # 毫秒
                total_time = self.video_player.get_length()  # 毫秒
                if total_time > 0:
                    progress = current_time / total_time * 1000
                    self.scale.set(progress)
                    current_str = self.format_time(current_time // 1000)
                    total_str = self.format_time(total_time // 1000)
                    self.time_label.config(text=f"{current_str} / {total_str}")
            else:
                # 如果视频不在播放 或 正在拖动，则不更新进度条
                if self.video_player is None or not self.video_player.is_playing():
                    self.scale.set(0)
                    self.time_label.config(text="00:00:00 / 00:00:00")
        except Exception as e:
            logging.error(f"更新进度条时出错: {e}")
        finally:
            # 每1000毫秒更新一次
            self.root.after(1000, self.update_progress)

    def format_time(self, seconds):
        h = seconds // 3600
        m = (seconds % 3600) // 60
        s = seconds % 60
        return f"{h:02}:{m:02}:{s:02}"

    def close_video(self):
        """关闭/停止视频和音频，销毁窗口"""
        if self.video_player is not None:
            self.video_player.stop()
            self.video_player = None

        if self.audio_player is not None:
            self.audio_player.stop()
            self.audio_player = None

        # 关闭窗口（如果存在）
        if hasattr(self, "video_window"):
            self.video_window.destroy()
            del self.video_window

        if hasattr(self, "audio_window"):
            self.audio_window.destroy()
            del self.audio_window

        self.pause_button.config(state=tk.DISABLED, text="暂停")
        self.scale.set(0)
        self.time_label.config(text="00:00:00 / 00:00:00")
if __name__ == "__main__":
    root = tk.Tk()
    app = MediaPlayerApp(root)
    root.mainloop()

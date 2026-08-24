import os
import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import yt_dlp
import markdown
from google import genai

# 1. 监控的频道列表（同时支持常规视频 /videos 和直播回放 /streams）
CHANNELS = [
    {
        "name": "私募一哥常士杉",
        "urls": [
            "https://www.youtube.com/@%E7%A7%81%E5%8B%9F%E4%B8%80%E5%93%A5%E5%B8%B8%E5%A3%AB%E6%9D%89/streams",
            "https://www.youtube.com/@%E7%A7%81%E5%8B%9F%E4%B8%80%E5%93%A5%E5%B8%B8%E5%A3%AB%E6%9D%89/videos"
        ]
    },
    {
        "name": "RhinoFinance",
        "urls": [
            "https://www.youtube.com/@RhinoFinance/videos"
        ]
    }
]

HISTORY_FILE = "processed_videos.json"

def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def save_history(history):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

def get_latest_videos(channel_urls, max_check=2):
    """获取频道最新发布的视频 ID 和标题"""
    videos = []
    ydl_opts = {
        'extract_flat': True,
        'playlistend': max_check,
        'quiet': True,
        'no_warnings': True
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        for url in channel_urls:
            try:
                info = ydl.extract_info(url, download=False)
                if 'entries' in info:
                    for entry in info['entries']:
                        if entry:
                            videos.append({
                                'id': entry.get('id'),
                                'title': entry.get('title'),
                                'url': f"https://www.youtube.com/watch?v={entry.get('id')}"
                            })
            except Exception as e:
                print(f"抓取频道页面失败 {url}: {e}")
    return videos

def download_audio(video_url, output_path="temp_audio.mp3"):
    """仅下载压缩音频，极大提升速度并节省空间"""
    if os.path.exists(output_path):
        os.remove(output_path)
        
    ydl_opts = {
        'format': 'ba[ext=m4a]/ba/b',
        'outtmpl': 'temp_audio.%(ext)s',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '64', # 64kbps 对人声识别完全足够且体积极小
        }],
        'quiet': True,
        'no_warnings': True
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([video_url])
    return output_path

def summarize_with_gemini(audio_path, channel_name, video_title, video_url):
    """通过 Gemini 官方 SDK 直接上传音频并进行深度结构化总结"""
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    
    print(f"正在上传音频到 Gemini File API: {video_title}...")
    uploaded_file = client.files.upload(file=audio_path)
    
    prompt = f"""
你是一位资深的金融与宏观市场分析助理。这是 YouTube 财经频道【{channel_name}】最新发布的视频/直播音频。
视频标题：{video_title}
视频链接：{video_url}

由于该视频没有字幕，请直接根据音频内容进行准确、深度的结构化总结与信息提取。

请按以下格式输出结构化中文报告：
# 📊 【{channel_name}】最新视频观点精要
**视频标题**：{video_title}
**原片链接**：{video_url}

---

### 一、 💡 核心主题与大盘/宏观定调（2-3句话总结）

### 二、 📌 核心交易/投资逻辑与关键观点（分条列出最关键的论据）

### 三、 🎯 涉及板块、行业、重要标的及对应态度
* （梳理视频中重点讨论的行业/板块，如有提及具体标的或公司，说明作者的核心逻辑是看多、看空还是中性观察）

### 四、 ⏱️ 时间线与重要讨论脉络
* [大概时间戳] 讨论话题及关键细节

### 五、 ⚠️ 风险提示与操作策略总结（如有）
"""
    print("Gemini 正在分析音频并生成总结...")
    # 使用兼具超长音频理解与极高速度的 flash 模型
    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=[uploaded_file, prompt]
    )
    
    # 清理远程云端缓存文件
    try:
        client.files.delete(name=uploaded_file.name)
    except Exception:
        pass
        
    return response.text

def send_email(subject, markdown_body):
    """发送 HTML 格式邮件"""
    sender = os.environ["SENDER_EMAIL"]
    password = os.environ["SENDER_PASSWORD"]
    receiver = os.environ["RECEIVER_EMAIL"]
    
    # 将 Markdown 转换为排版良好的 HTML 邮件
    html_content = markdown.markdown(markdown_body, extensions=['extra', 'tables'])
    styled_html = f"""
    <html>
      <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; line-height: 1.6; color: #2d3748; max-width: 800px; margin: 0 auto; padding: 20px;">
        <div style="background-color: #f7fafc; border-left: 4px solid #3182ce; padding: 15px 20px; border-radius: 4px; margin-bottom: 20px;">
          <h2 style="margin: 0; color: #2b6cb0;">YouTube 财经频道每日观点简报</h2>
        </div>
        {html_content}
        <hr style="border: 0; border-top: 1px solid #e2e8f0; margin-top: 30px;">
        <p style="font-size: 12px; color: #a0aec0;">本邮件由 Gemini 自动化分析服务生成并推送。</p>
      </body>
    </html>
    """
    
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"Gemini Finance Bot <{sender}>"
    msg["To"] = receiver
    msg.attach(MIMEText(styled_html, "html", "utf-8"))
    
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(sender, password)
        server.sendmail(sender, receiver, msg.as_string())
    print("邮件发送成功！")

def main():
    history = load_history()
    new_history = list(history)
    
    for channel in CHANNELS:
        name = channel["name"]
        print(f"正在扫描频道: {name}...")
        latest_videos = get_latest_videos(channel["urls"])
        
        for video in latest_videos:
            v_id = video["id"]
            if not v_id or v_id in history:
                continue
                
            print(f"发现新视频: {video['title']} ({video['url']})")
            try:
                # 1. 下载音频
                audio_file = download_audio(video['url'])
                
                # 2. Gemini 听音频并总结
                summary = summarize_with_gemini(audio_file, name, video['title'], video['url'])
                
                # 3. 发送邮件
                subject = f"【YouTube总结】{name}：{video['title']}"
                send_email(subject, summary)
                
                # 4. 记录已处理
                new_history.append(v_id)
                
                # 清理本地临时音频
                if os.path.exists(audio_file):
                    os.remove(audio_file)
            except Exception as e:
                print(f"处理视频失败 {video['title']}: {e}")
                
    save_history(new_history)

if __name__ == "__main__":
    main()

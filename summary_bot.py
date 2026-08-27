import os
import json
import time
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import yt_dlp
import markdown
from google import genai
from google.genai import types

# 监控的 YouTube 频道配置（指定直播 streams 或常规录播 videos）
CHANNELS = [
    {
        "name": "私募一哥常士杉",
        "channel_id": "UCq_6F1GwN58l_OZaQgFHNrg",
        "tab": "streams"   # 常士杉主打直播回放
    },
    {
        "name": "视野环球财经",
        "channel_id": "UCFQsi7WaF5X41tcuOryDk8w",
        "tab": "videos"    # RhinoFinance 主打常规视频
    }
]

HISTORY_FILE = "processed_videos.json"

def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def save_history(history):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

def get_channel_latest_videos(channel_id, tab="videos", max_check=2):
    """使用 yt-dlp 精准提取目标标签页（streams 或 videos）的最新内容"""
    ydl_opts = {
        'extract_flat': True,
        'quiet': True,
        'no_warnings': True,
        'playlist_items': f'1-{max_check}',
    }
    url = f"https://www.youtube.com/channel/{channel_id}/{tab}"
    videos = []
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if info and 'entries' in info:
                for entry in info['entries']:
                    if not entry:
                        continue
                    v_id = entry.get('id')
                    v_title = entry.get('title')
                    if v_id and v_title:
                        videos.append({
                            'id': v_id,
                            'title': v_title,
                            'url': f"https://www.youtube.com/watch?v={v_id}"
                        })
    except Exception as e:
        print(f"  └ 提取 [{tab}] 标签页失败 ({channel_id}): {e}")
        
    return videos[:max_check]

def summarize_with_gemini(channel_name, video_title, video_url, max_retries=3):
    # 设置 300 秒长超时，防止长直播分析期间连接中断
    client = genai.Client(
        api_key=os.environ["GEMINI_API_KEY"],
        http_options={'timeout': 300000}
    )
    
    prompt = f"""
你是一位资深的金融与宏观市场分析助理。这是 YouTube 财经频道【{channel_name}】最新发布的视频/直播：
视频标题：{video_title}
视频链接：{video_url}

即使视频没有字幕，请直接根据视频/音频内容进行精准、深度的结构化总结与信息提取。

请按以下格式输出结构化中文简报：
# 📊 【{channel_name}】最新观点精要
**视频标题**：{video_title}
**原片链接**：{video_url}

---

### 一、 💡 核心主题与大盘/宏观定调（2-3句话总结）

### 二、 📌 核心交易/投资逻辑与关键观点（分条列出最关键的论据）

### 三、 🎯 涉及板块、行业、重要标的及对应态度
* （梳理重点讨论的行业/板块，如有提及具体标的或公司，说明核心逻辑是看多、看空还是中性）

### 四、 ⏱️ 时间线与重要讨论脉络
* [大概时间戳] 讨论话题及关键细节

### 五、 ⚠️ 风险提示与操作策略总结（如有）
"""
    for attempt in range(1, max_retries + 1):
        try:
            print(f"正在请求 Google Gemini Flash 分析: {video_title} (第 {attempt}/{max_retries} 次尝试)...")
            response = client.models.generate_content(
                model='gemini-3.7-flash',
                contents=types.Content(
                    parts=[
                        types.Part(file_data=types.FileData(file_uri=video_url)),
                        types.Part(text=prompt)
                    ]
                )
            )
            return response.text
        except Exception as e:
            err_str = str(e).lower()
            # 捕获限流、503 拥堵以及长连接断开/超时异常
            is_retryable = any(keyword in err_str for keyword in [
                "503", "unavailable", "429", "resource_exhausted",
                "disconnected", "timeout", "timed out", "connectionreset", "remotedisconnected"
            ])
            
            if is_retryable and attempt < max_retries:
                wait_seconds = attempt * 35
                print(f"⚠️ 遇到临时异常（网络断连/服务端限流），等待 {wait_seconds} 秒后重试...")
                time.sleep(wait_seconds)
            else:
                raise e

def send_email(subject, markdown_body):
    sender = os.environ["SENDER_EMAIL"]
    password = os.environ["SENDER_PASSWORD"]
    receiver = os.environ["RECEIVER_EMAIL"]
    
    html_content = markdown.markdown(markdown_body, extensions=['extra', 'tables'])
    styled_html = f"""
    <html>
      <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; line-height: 1.6; color: #2d3748; max-width: 800px; margin: 0 auto; padding: 20px;">
        <div style="background-color: #f7fafc; border-left: 4px solid #3182ce; padding: 15px 20px; border-radius: 4px; margin-bottom: 20px;">
          <h2 style="margin: 0; color: #2b6cb0;">YouTube 财经频道观点简报</h2>
        </div>
        {html_content}
        <hr style="border: 0; border-top: 1px solid #e2e8f0; margin-top: 30px;">
        <p style="font-size: 12px; color: #a0aec0;">本邮件由 Google Gemini 自动化分析服务生成并推送。</p>
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
    print(">>> ✅ 邮件发送成功！")

def main():
    history = load_history()
    new_history = list(history)
    
    for channel in CHANNELS:
        name = channel["name"]
        cid = channel["channel_id"]
        tab = channel.get("tab", "videos")
        print(f"\n==========================================")
        print(f"正在扫描频道: {name} (ID: {cid} | 来源: {tab})")
        
        try:
            latest_videos = get_channel_latest_videos(cid, tab=tab, max_check=2)
            print(f"成功获取到 {len(latest_videos)} 个最新内容。")
            
            for video in latest_videos:
                v_id = video["id"]
                print(f"- 检查 [{v_id}]: {video['title']}")
                if v_id in history:
                    print(f"  └ 该视频/直播已在历史记录中，跳过。")
                    continue
                    
                print(f"  └ 发现新内容，交给 Gemini Flash 分析中...")
                summary = summarize_with_gemini(name, video['title'], video['url'])
                
                raw_title = video['title']
                short_title = raw_title[:32] + "..." if len(raw_title) > 32 else raw_title
                subject = f"【YT精要】{name}：{short_title}"
                
                send_email(subject, summary)
                
                new_history.append(v_id)
                
                print("已处理完一个视频，休眠 60 秒以恢复免费 Token 额度...")
                time.sleep(60)
                    
        except Exception as e:
            print(f"处理频道 [{name}] 出现异常: {e}")
                
    save_history(new_history)
    print("\n所有频道监控任务已完成。")

if __name__ == "__main__":
    main()

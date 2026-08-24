import os
import json
import smtplib
import urllib.request
import xml.etree.ElementTree as ET
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import markdown
from google import genai
from google.genai import types

# 监控的 YouTube 频道配置（频道 ID 区分大小写）
CHANNELS = [
    {
        "name": "私募一哥常士杉",
        "channel_id": "UCq_6F1GwN58l_OZaQgFHNrg"
    },
    {
        "name": "RhinoFinance",
        "channel_id": "UCFQsi7WaF5X41tcuOryDk8w"
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

def get_latest_videos_rss(channel_id, max_check=2):
    """通过 YouTube 官方 RSS 接口获取最新视频列表"""
    rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    req = urllib.request.Request(
        rss_url,
        headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
    )
    videos = []
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            xml_data = resp.read()
            root = ET.fromstring(xml_data)
            ns = {
                'atom': 'http://www.w3.org/2005/Atom',
                'yt': 'http://www.youtube.com/xml/schemas/2015'
            }
            entries = root.findall('atom:entry', ns)
            for entry in entries[:max_check]:
                v_id_el = entry.find('yt:videoId', ns)
                title_el = entry.find('atom:title', ns)
                if v_id_el is not None and title_el is not None:
                    videos.append({
                        'id': v_id_el.text,
                        'title': title_el.text,
                        'url': f"https://www.youtube.com/watch?v={v_id_el.text}"
                    })
    except Exception as e:
        print(f"获取频道 RSS 失败 ({channel_id}): {e}")
    return videos

def summarize_with_gemini(channel_name, video_title, video_url):
    """使用 Gemini 原生 YouTube URL 直连理解能力"""
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    
    prompt = f"""
你是一位资深的金融与宏观市场分析助理。这是 YouTube 财经频道【{channel_name}】最新发布的视频/直播：
视频标题：{video_title}
视频链接：{video_url}

即使视频没有字幕，请直接根据视频/音频内容进行精准、深度的结构化总结与信息提取。

请按以下格式输出结构化中文简报：
# 📊 【{channel_name}】最新视频观点精要
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
    print(f"正在请求 Google Gemini 官方服务器直连分析 YouTube: {video_url}...")
    
    # 核心：直接向 Gemini 传入 YouTube URL，由 Google 后端直读，免除本地下载
    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=types.Content(
            parts=[
                types.Part(
                    file_data=types.FileData(file_uri=video_url)
                ),
                types.Part(text=prompt)
            ]
        )
    )
    return response.text

def send_email(subject, markdown_body):
    """发送 HTML 排版邮件"""
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
    print(">>> 邮件发送成功！")

def main():
    history = load_history()
    new_history = list(history)
    
    for channel in CHANNELS:
        name = channel["name"]
        cid = channel["channel_id"]
        print(f"\n==========================================")
        print(f"正在扫描频道: {name} (ID: {cid})")
        
        try:
            latest_videos = get_latest_videos_rss(cid, max_check=2)
            print(f"成功获取到 {len(latest_videos)} 个最新视频。")
            
            for video in latest_videos:
                v_id = video["id"]
                print(f"- 检查视频 [{v_id}]: {video['title']}")
                if v_id in history:
                    print(f"  └ 该视频已在历史记录中，跳过。")
                    continue
                    
                print(f"  └ 发现新视频，交给 Gemini 分析中...")
                summary = summarize_with_gemini(name, video['title'], video['url'])
                
                subject = f"【YouTube总结】{name}：{video['title']}"
                send_email(subject, summary)
                
                new_history.append(v_id)
                    
        except Exception as e:
            print(f"处理频道 [{name}] 出现异常: {e}")
                
    save_history(new_history)
    print("\n所有频道监控任务已完成。")

if __name__ == "__main__":
    main()

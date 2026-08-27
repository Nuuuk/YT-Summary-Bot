import os
import json
import time
import re
import smtplib
import urllib.request
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import markdown
from google import genai
from google.genai import types

# 监控的 YouTube 频道配置
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

def extract_videos_from_json(data):
    """从 YouTube 内部 JSON 结构中递归提取视频 ID 与标题"""
    results = []
    def recurse(node):
        if isinstance(node, dict):
            if "videoId" in node and "title" in node:
                v_id = node["videoId"]
                title_obj = node["title"]
                title = ""
                if isinstance(title_obj, dict):
                    if "runs" in title_obj and title_obj["runs"]:
                        title = "".join([r.get("text", "") for r in title_obj["runs"]])
                    elif "simpleText" in title_obj:
                        title = title_obj.get("simpleText", "")
                elif isinstance(title_obj, str):
                    title = title_obj
                
                if isinstance(v_id, str) and len(v_id) == 11 and title:
                    results.append({
                        'id': v_id,
                        'title': title,
                        'url': f"https://www.youtube.com/watch?v={v_id}"
                    })
            for v in node.values():
                recurse(v)
        elif isinstance(node, list):
            for item in node:
                recurse(item)
    recurse(data)
    
    # 保持原网页顺序去重
    seen = set()
    deduped = []
    for r in results:
        if r['id'] not in seen:
            seen.add(r['id'])
            deduped.append(r)
    return deduped

def get_videos_from_tab(channel_id, tab="streams", limit=2):
    """直接解析 YouTube 频道的 streams(直播) 或 videos(录播) 页面"""
    url = f"https://www.youtube.com/channel/{channel_id}/{tab}"
    req = urllib.request.Request(
        url,
        headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8'
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode('utf-8', errors='ignore')
            m = re.search(r'ytInitialData\s*=\s*', html)
            if m:
                data = json.JSONDecoder().raw_decode(html[m.end():])[0]
                videos = extract_videos_from_json(data)
                return videos[:limit]
    except Exception as e:
        print(f"  └ 抓取 [{tab}] 标签页出现异常 ({channel_id}): {e}")
    return []

def get_channel_latest_videos(channel_id, max_check=2):
    """同时获取最新的直播流与常规视频，确保零遗漏"""
    streams = get_videos_from_tab(channel_id, tab="streams", limit=max_check)
    videos = get_videos_from_tab(channel_id, tab="videos", limit=max_check)
    
    combined = []
    seen = set()
    # 优先收录最新直播，再收录最新录播视频
    for v in streams + videos:
        if v['id'] not in seen:
            seen.add(v['id'])
            combined.append(v)
            
    return combined

def summarize_with_gemini(channel_name, video_title, video_url, max_retries=3):
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    
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
            print(f"正在请求 Google Gemini 分析: {video_title} (第 {attempt}/{max_retries} 次尝试)...")
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
            err_str = str(e)
            if ("503" in err_str or "UNAVAILABLE" in err_str or "429" in err_str) and attempt < max_retries:
                wait_seconds = attempt * 30
                print(f"⚠️ 遇到临时服务器拥堵/限流 (503/429)，等待 {wait_seconds} 秒后重试...")
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
        print(f"\n==========================================")
        print(f"正在扫描频道: {name} (ID: {cid})")
        
        try:
            latest_videos = get_channel_latest_videos(cid, max_check=2)
            print(f"成功获取到 {len(latest_videos)} 个最新内容候选。")
            
            for video in latest_videos:
                v_id = video["id"]
                print(f"- 检查 [{v_id}]: {video['title']}")
                if v_id in history:
                    print(f"  └ 该视频/直播已在历史记录中，跳过。")
                    continue
                    
                print(f"  └ 发现新内容，交给 Gemini 分析中...")
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

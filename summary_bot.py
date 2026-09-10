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
        "tab": "streams"   # 直播回放
    },
    {
        "name": "视野环球财经",
        "channel_id": "UCFQsi7WaF5X41tcuOryDk8w",
        "tab": "videos"    # 常规录播视频
    }
]

HISTORY_FILE = "processed_videos.json"

# 从环境变量读取，支持用逗号分隔配置多个模型；若未配置则使用默认排序
env_models = os.environ.get("GEMINI_MODELS")
if env_models:
    MODELS_PRIORITY = [m.strip() for m in env_models.split(",") if m.strip()]
else:
    MODELS_PRIORITY = ['gemini-3.8-flash', 'gemini-3.7-flash', 'gemini-3.6-flash']

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
    """使用 yt-dlp 精准提取目标标签页的最新内容元数据"""
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

def summarize_with_gemini(channel_name, video_title, video_url, max_retries_per_model=2):
    """3级模型自动轮换降级与网络断连自动重试机制"""
    client = genai.Client(
        api_key=os.environ["GEMINI_API_KEY"],
        http_options={'timeout': 300000}  # 5分钟超时保护
    )
    
    prompt = f"""
你是一位资深的金融与宏观市场分析助理。

请分析 YouTube 财经频道【{channel_name}】最新发布的视频/直播，并对其中的内容进行准确、深度、结构化总结。

视频标题：{video_title}
视频链接：{video_url}

即使视频没有字幕，也请尽可能根据视频/音频内容提取信息。

你的首要任务是：
准确理解作者在视频中表达的观点、论证、数据、判断和操作思路，
并重建作者原本的“观点结构”和“逻辑层级”。

不要机械地逐句总结，也不要把所有观点简单地排列成一个扁平列表。
要根据语义主动判断：
哪些是总体判断，哪些是其展开；
哪些是主论点，哪些是分论点；
哪些是原则，哪些是具体执行方式；
哪些内容彼此独立，哪些内容实际上属于同一个观点。

Markdown 只是表达这种逻辑结构的工具，不要让 Markdown 的格式反过来决定观点的层级。

==================================================
一、观点结构与主次关系
==================================================

请首先在内部理解并建立作者观点之间的自然层级，然后再生成最终答案。

当多个观点之间存在自然的“总—分、上位—下位、原则—具体做法、策略—子策略、总体判断—具体表现、类别—具体项目”等关系时，应保留这种从属关系。

如果一个观点是在进一步解释、展开、落实或具体化另一个观点，
它应当属于前一个观点，而不是被提升成与其并列的独立观点。

如果两个观点在语义上彼此独立、分别表达不同的核心判断，则可以作为并列观点。

不要因为几个观点：
- 都很重要
- 都很短
- 都是完整句子
- 都是动词开头
- 都属于交易建议
- 都是在连续几句话中出现

就自动把它们视为同一级。

尤其不要为了让结构看起来整齐，而主动把原本具有父子关系的观点“扁平化”。

例如，如果作者的意思是：

“严守交易纪律，具体包括不追高、逆向低吸和动态止盈。”

正确理解应该是：

严守交易纪律
├── 不追高
├── 逆向低吸
└── 动态止盈

而不是把“严守交易纪律”“不追高”“逆向低吸”“动态止盈”
机械地处理成四个并列观点。

同样，如果多个内容实际上都是同一个观点的不同依据、数据、案例或执行细节，也不要人为拆成多个主论点。

你的目标不是让每句话都有一个层级，而是让读者一眼看出：
“什么是核心观点，什么是在解释这个核心观点。”

==================================================
二、输出结构
==================================================

请按照以下五个一级章节组织最终答案。

一级章节使用：

### 一、...
### 二、...
### 三、...
### 四、...
### 五、...

二级层级使用：

#### 核心观点或主题

观点下面的展开内容使用：

* **字段/分论点**：具体内容

注意：

“*” 不仅可以用于普通细节，也可以用于表达某个主论点下面的分论点。

因此，出现下面这种结构是完全合理的：

#### 严守交易铁律

* **绝不追高**：……
* **逆向低吸**：……
* **动态止盈**：……

这里的三个“*”属于“严守交易铁律”的展开内容，
不能因为它们本身也是完整的交易规则，
就自动提升成新的 #### 主观点。

只有语义上真正独立的主张，才应使用新的 ####。

不要为了追求形式统一而强行让所有 #### 下面都有相同数量的 * 条目。

==================================================
三、Markdown 使用原则
==================================================

请避免使用 Markdown 数字有序列表来表达观点层级。

不要把核心观点机械写成：

1. 观点A
2. 观点B
3. 观点C
4. 观点D

也不要为了编号而写成：

#### 1. 观点A
#### 2. 观点B
#### 3. 观点C

核心观点之间的主次关系应该通过 Markdown 的层级以及内容本身的语义关系体现，而不是通过数字编号体现。

一级章节仍然使用“### 一、二、三、四、五”的形式。

不要为了“分条列出”而把原本具有从属关系的内容拆成平级条目。

==================================================
四、具体输出内容
==================================================

# 📊 【{channel_name}】最新观点精要

**视频标题**：{video_title}
**原片链接**：{video_url}

---

### 一、💡核心主题与大盘/宏观定调

用 2-3 句话概括整个视频最重要的宏观环境、市场判断和总体基调。

这里重点回答：

作者认为当前市场处于什么状态？
最值得关注的核心变量是什么？
整体偏多、偏空、谨慎还是结构性机会？

不要把这一部分写成简单的观点列表。

---

### 二、📌核心交易/投资逻辑与关键观点

提取视频中最重要的交易、投资、宏观或市场逻辑。

重点不是“列出多少条”，而是准确还原作者的逻辑结构。

对于每个真正独立的核心观点，可以使用：

#### 核心观点

* **核心逻辑**：……
* **数据支撑**：……
* **关键变量**：……
* **风险因素**：……
* **操作结论**：……

但不要机械填充上述所有字段。
只有视频中确实存在的信息才提取。

如果一个核心观点下面存在多个分论点，应保留这种关系，例如：

#### 严守交易纪律

* **绝不追高**：……
* **逆向低吸**：……
* **动态止盈**：……

而不是：

#### 严守交易纪律
#### 绝不追高
#### 逆向低吸
#### 动态止盈

---

### 三、🎯涉及板块、行业、重要标的及对应态度

按照自然的行业、主题或投资逻辑进行归类。

只有真正独立的行业/主题才作为新的 #### 层级。

例如：

#### 美股科技与卫星数据

* **PL（Planet Labs PBC）**（态度：看多）：……
* **相关逻辑/其他标的**：……

#### 半导体与算力硬件

* **NVDA（NVIDIA）**（态度：谨慎/中性）：……
* **AVGO（Broadcom）**（态度：逢低参与）：……

不要机械按照股票出现顺序排列。
如果几个标的实际上共同服务于同一个行业或投资逻辑，应归入同一主题。

对于具体标的，尽可能提取视频明确提及的：

* **态度**
* **核心理由**
* **关键价格**
* **目标区间**
* **支撑/压力**
* **风险因素**
* **操作思路**

不要自行创造作者没有明确表达的目标价、评级或交易结论。

---

### 四、⏱️时间线与重要讨论脉络

按照视频中的实际讨论顺序或重要时间节点整理。

使用 * 无序列表，例如：

* **[大概时间戳]**：讨论全球宏观环境及政策窗口。
* **[大概时间戳]**：讨论A股/科创板。
* **[大概时间戳]**：讨论具体个股或行业。

不要使用数字有序列表。

如果无法可靠获得时间戳，可以省略时间戳，
但应尽量保留视频的讨论脉络。

---

### 五、⚠️风险提示与操作策略总结

这一部分尤其需要保留作者原本的主次关系。

不要简单地把所有风险和操作建议平铺成一个列表。

先判断哪些属于更高层次的总体策略，
哪些属于该策略下面的具体执行原则或分策略。

例如，如果作者表达：

“当前政策窗口期需要降低风险敞口，同时严格遵守交易纪律，包括不追高、逆向低吸和动态止盈。”

应理解为：

#### 政策窗口期控制风险敞口

* **重点防范时点**：……
* **潜在风险**：……
* **仓位策略**：……

#### 严守交易铁律

* **绝不追高**：……
* **逆向低吸**：……
* **动态止盈**：……

而不是把：

“严守交易铁律”
“绝不追高”
“逆向低吸”
“动态止盈”

全部当作并列的主论点。

同样，也不要反过来强行制造层级。
如果作者明确表达的是彼此独立的几个风险，则应该保持其独立性。

如果视频没有明确的风险提示或操作策略，则写：

* **未发现明确的风险提示或操作策略。**

==================================================
五、信息真实性与观点归属
==================================================

1. 忠实还原视频作者的观点，不要将你的个人投资观点混入作者观点。

2. 不要为了让总结更加完整而补充视频中没有出现的推论。

3. 对无法确认的信息，不要编造具体数字、价格、日期、公司名称或结论。

4. 如果公司名称、股票代码、数据或专业术语存在明显识别不确定性，应明确说明，而不是猜测。

5. 作者的观点与客观事实应尽量区分。
例如：
“作者认为……”
“视频中提到……”
“数据显示……”
避免把作者的判断写成无争议的客观事实。

6. 对同一观点的重复表达应适当合并，避免因为作者重复强调而产生多个虚假的独立观点。

7. 不要以“观点数量”作为结构目标。
观点有多少取决于视频内容本身。

==================================================
六、结构质量要求
==================================================

最终答案应满足：

第一，信息完整。
第二，逻辑清晰。
第三，主次分明。
第四，尽量保留作者原有的论述关系。
第五，避免把复杂观点压扁成简单的并列列表。

尤其注意：

“结构化”不等于“列表化”。

一个好的总结应该让读者能够看出：

什么是一级主题；
什么是核心观点；
什么是该观点的分论点；
什么只是数据、依据、案例或执行细节。

不要为了 Markdown 的整齐，
牺牲真实的语义层级。

==================================================
七、最终内部检查
==================================================

生成最终答案之前，请在内部重新检查一次：

是否错误地把属于同一个主论点的多个分论点扁平化了？

是否错误地把某个主论点和它的具体执行方式放成了同一级？

是否把真正独立的观点错误地合并？

Markdown 层级是否准确反映了你对作者观点结构的理解？

不要输出检查过程，只输出最终结果。

现在开始分析视频内容，并按照上述原则生成最终答案。
"""
    last_exception = None

    for model_name in MODELS_PRIORITY:
        for attempt in range(1, max_retries_per_model + 1):
            try:
                print(f"正在使用 [{model_name}] 进行分析 (第 {attempt}/{max_retries_per_model} 次)...")
                response = client.models.generate_content(
                    model=model_name,
                    contents=types.Content(
                        parts=[
                            types.Part(file_data=types.FileData(file_uri=video_url)),
                            types.Part(text=prompt)
                        ]
                    )
                )
                return response.text
            except Exception as e:
                last_exception = e
                err_str = str(e).lower()
                is_retryable = any(k in err_str for k in [
                    "503", "unavailable", "429", "resource_exhausted",
                    "disconnected", "timeout", "timed out", "connectionreset", "remotedisconnected"
                ])
                if is_retryable and attempt < max_retries_per_model:
                    wait_sec = 30 * attempt
                    print(f"⚠️ [{model_name}] 遇到服务器拥堵/网络抖动，等待 {wait_sec} 秒后重试...")
                    time.sleep(wait_sec)
                else:
                    break
        
        print(f"🔄 模型 [{model_name}] 暂时无法响应，正在自动切换至下一个模型...")

    raise last_exception

def send_email(subject, markdown_body):
    sender = os.environ["SENDER_EMAIL"]
    password = os.environ["SENDER_PASSWORD"]
    receiver = os.environ["RECEIVER_EMAIL"]
    
    html_content = markdown.markdown(markdown_body, extensions=['extra', 'tables'])
    styled_html = f"""
    <html>
      <head>
        <style>
          body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; line-height: 1.6; color: #2d3748; max-width: 800px; margin: 0 auto; padding: 20px; }}
          .header-box {{ background-color: #f7fafc; border-left: 4px solid #3182ce; padding: 15px 20px; border-radius: 4px; margin-bottom: 20px; }}
          h1 {{ font-size: 20px; color: #2b6cb0; margin: 0; }}
          h3 {{ font-size: 16px; color: #2c5282; border-bottom: 2px solid #edf2f7; padding-bottom: 6px; margin-top: 25px; }}
          h4 {{ font-size: 14px; color: #2b6cb0; margin-top: 15px; margin-bottom: 6px; }}
          ul {{ margin-top: 4px; padding-left: 20px; }}
          li {{ margin-bottom: 6px; font-size: 14px; }}
        </style>
      </head>
      <body>
        <div class="header-box">
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
                    
                print(f"  └ 发现新内容，交给 Gemini 自动分析中...")
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

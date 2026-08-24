YouTube AI Summary Bot

An automated, serverless pipeline using Google Gemini Multimodal API and GitHub Actions to monitor YouTube channels, summarize new videos and livestreams (even without subtitles), and deliver structured executive reports directly to your email.

✨ Features

No Subtitles Needed: Native audio/video understanding via Google Gemini.

Serverless & Free: Runs on GitHub Actions scheduled cron jobs at zero hosting cost.

Smart Deduplication: Automatically tracks processed videos via processed_videos.json to prevent duplicates.

Email Delivery: Formats summaries into clean, responsive HTML emails via SMTP.

🚀 Quick Setup

Add the following Secrets in Settings > Secrets and variables > Actions:

GEMINI_API_KEY: Google AI Studio API key.

SENDER_EMAIL: Sender email address (e.g., Gmail).

SENDER_PASSWORD: Email 16-character App Password.

RECEIVER_EMAIL: Recipient email address.

Edit CHANNELS in summary_bot.py with target Channel IDs (UC...).

Trigger manually in the Actions tab or let it run on schedule.

YouTube AI 视频观点总结机器人

基于 Google Gemini 原生多模态 API 与 GitHub Actions 的无服务器自动化工具。定时监控指定 YouTube 频道，自动深度提炼最新视频及长直播要点（无需字幕），并以结构化 HTML 邮件形式推送到指定邮箱。

✨ 核心特性

无字幕原生理解：基于 Gemini 多模态能力，直接听取并分析音视频内容。

零成本免运维：由 GitHub Actions 定时任务驱动，无需购买云服务器。

智能去重防扰：通过 processed_videos.json 自动记录已处理视频，避免重复推送。

排版邮件推送：自动将 Markdown 总结转换为精美 HTML 邮件发送。

🚀 快速配置

在 GitHub 仓库的 Settings > Secrets and variables > Actions 中添加配置：

GEMINI_API_KEY：Google AI Studio API 密钥。

SENDER_EMAIL：发件邮箱（如 Gmail）。

SENDER_PASSWORD：邮箱 16 位应用专用密码。

RECEIVER_EMAIL：接收报告的邮箱地址。

在 summary_bot.py 中更新 CHANNELS 列表对应的 YouTube 频道 ID（以 UC 开头）。

在 Actions 页面手动点击 Run workflow 运行测试，或等待定时任务自动触发。

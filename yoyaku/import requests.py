import requests

DISCORD_WEBHOOK_URL = "https://discordapp.com/api/webhooks/1398139112413859982/K8iKLKKaZe-o3SbrbiJv6Et69EQOQdXfL9qAMRc-ddaEa3tquhPlpyfcM-HlsMCVUj6E"

message = {
    "content": "✅ Webhook テスト送信成功！"
}

response = requests.post(DISCORD_WEBHOOK_URL, json=message)

print(f"ステータスコード: {response.status_code}")
print(f"レスポンス内容: {response.text}")

from openrouter import OpenRouter
from dotenv import load_dotenv
import os

load_dotenv()

HC_API = os.getenv("HC_API")

client = OpenRouter(
    api_key=HC_API,
    server_url="https://ai.hackclub.com/proxy/v1",
)

def qwen(prompt):
    response = client.chat.send(
        model="qwen/qwen3-32b",
        messages=[
            {"role": "user", "content": prompt}
        ],
        stream=False,
    )
    return (response.choices[0].message.content)

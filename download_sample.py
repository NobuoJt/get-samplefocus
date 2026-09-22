import asyncio
import re
import sys
from urllib.parse import quote
import httpx
from playwright.async_api import async_playwright

BASE_URL = "https://samplefocus.com"


async def download_mp3_from_search(
    page, search_query: str
) -> str | None:
    """検索ページ上で直接再生ボタンを押し、MP3 URLを横取りする"""
    mp3_url = None

    # 1. バックグラウンド通信を監視し、CloudFront等の .mp3 リクエストをキャプチャ
    def handle_request(request):
        nonlocal mp3_url
        url = request.url
        if ".mp3" in url:
            mp3_url = url
            print(f"⚡ MP3 リクエストをキャプチャ: {mp3_url}")

    page.on("request", handle_request)

    encoded_query = quote(search_query)
    search_url = f"{BASE_URL}/samples?search={encoded_query}"
    print(f"🔍 検索ページにアクセス中: {search_url}")

    # 検索ページへ移動
    await page.goto(search_url, wait_until="domcontentloaded")

    # 2. カードコンテナ (#samples) の描画を待機
    try:
        await page.wait_for_selector("#samples", timeout=10000)
    except Exception:
        print("⚠️ #samples の表示待機タイムアウト。続行します...")

    # 3. 最初のサンプルの再生ボタンセレクターを特定してクリック
    # 解析いただいた要素: .sf-card-action .card-action-button
    play_button_selector = "#samples .sf-card-action .card-action-button"

    try:
        print("⏳ 一覧上の再生ボタンの表示を待機中...")
        play_btn = page.locator(play_button_selector).first
        await play_btn.wait_for(state="visible", timeout=10000)

        print(
            "▶️ 検索結果上で再生ボタンをクリック（詳細ページへ行かずに通信を発火）..."
        )
        await play_btn.click()

        # クリック後、MP3の通信が発生するまで最大5秒待機
        for _ in range(10):
            if mp3_url:
                break
            await page.wait_for_timeout(500)

    except Exception as e:
        print(f"⚠️ 検索結果上での再生ボタンクリック失敗: {e}")

    # 4. リクエストから拾えなかった場合、ページ内のHTML/スクリプトからMP3直リンクを正規表現で探す
    if not mp3_url:
        print("👀 ページのHTML/スクリプト内から MP3 URL を探索中...")
        content = await page.content()
        match = re.search(r'https?://[^\s\'"]+\.mp3[^\s\'"]*', content)
        if match:
            mp3_url = match.group(0)

    return mp3_url


def verify_and_save_mp3(data: bytes, output_path: str) -> bool:
    """バイナリの冒頭ヘッダーを確認して MP3 として保存する"""
    if len(data) < 3:
        print("❌ エラー: 受信データが短すぎます。")
        return False

    header_bytes = data[:3]
    hex_str = " ".join([f"{b:02X}" for b in header_bytes])

    print(f"🔬 バイナリ冒頭 (Hex): {hex_str}")

    # 0x49 0x44 0x33 (ID3) の検証
    if header_bytes == b"ID3":
        print("✅ ID3 ヘッダーを確認しました (MP3ファイル)")
    else:
        print("⚠️ ID3 ヘッダーではありませんが、ファイルを保存します。")

    with open(output_path, "wb") as f:
        f.write(data)

    print(f"💾 ファイルを保存しました: {output_path}")
    return True


async def download_sample(keyword: str, output_filename: str = "downloaded.mp3"):
    async with async_playwright() as p:
        # Cloudflare対策: Headless Chrome でも各種プロパティを本物のブラウザに偽装
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-blink-features=AutomationControlled",  # Bot判定回避
            ],
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
        )
        page = await context.new_page()

        try:
            # 検索ページ上で直接 MP3 URL を取得
            mp3_url = await download_mp3_from_search(page, keyword)

            if not mp3_url:
                print("❌ MP3 リソースの URL を取得できませんでした。")
                return

            print(f"🎵 検出された MP3 URL: {mp3_url}")

            # 取得した MP3 URL をダウンロード (Referer を設定)
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    mp3_url,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                        "Referer": "https://samplefocus.com/",
                    },
                    follow_redirects=True,
                )

                if response.status_code == 200:
                    verify_and_save_mp3(response.content, output_filename)
                else:
                    print(
                        f"❌ ダウンロード失敗: HTTP ステータス {response.status_code}"
                    )

        except Exception as e:
            print(f"⚠️ エラーが発生しました: {e}")
        finally:
            await browser.close()


if __name__ == "__main__":
    query = "welcome to my world"
    if len(sys.argv) > 1:
        query = sys.argv[1]

    asyncio.run(download_sample(query, "welcome_to_my_world.mp3"))
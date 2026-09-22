import asyncio
import logging
import re
from urllib.parse import unquote
import httpx
from camoufox.async_api import AsyncCamoufox
from playwright.async_api import Response

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s]: %(message)s', datefmt='%H:%M:%S')

async def main():
    # Camoufox を非Headless（画面表示あり）で起動
    async with AsyncCamoufox(headless=False) as browser:
        page = await browser.new_page()

        # レスポンスのフック処理
        async def handle_response(response: Response):
          url = response.url
          # MP3通信かつレスポンス成功時
          if ('.mp3' in url or 'sample_files' in url) and response.status == 200:
              # 画像(波形・サムネイル等)を除外
              if any(ext in url for ext in ['.png', '.jpg', '.webp']):
                  return

              logging.info(f"🎧 MP3の通信を検知: {url}")

              title = "Unknown"
              author = "Unknown"
              bpm = "N/A"
              key = "N/A"
              duration = "N/A"

              try:
                  # --- 1. 現在再生中(fa-stop アイコンを持つ)カード要素を取得 ---
                  active_card = page.locator('.sf-card:has(i.fa-stop)').first
                  
                  # 再生中カードが取れない場合は、直近で触られたカードフォールバック
                  if await active_card.count() == 0:
                      active_card = page.locator('.sf-card').first

                  if await active_card.count() > 0:
                      # タイトル取得 (div[role="heading"])
                      title_elem = active_card.locator('div[role="heading"]')
                      if await title_elem.count() > 0:
                          title = (await title_elem.inner_text()).strip()

                      # 作者取得 (By の後ろにあるリンク)
                      author_elem = active_card.locator('.card-links a[aria-label="Link to author"]')
                      if await author_elem.count() > 0:
                          author = (await author_elem.inner_text()).strip()

                      # スペック情報 (BPM, Key, Duration) の取得 (ul.sample-attrs li)
                      attr_items = active_card.locator('ul.sample-attrs li')
                      count = await attr_items.count()
                      for i in range(count):
                          text = (await attr_items.nth(i).inner_text()).strip()
                          if 'bpm' in text.lower():
                              bpm = text
                          elif any(k in text for k in ['major', 'minor', 'Flat', 'Sharp', '#', '♭']) or re.search(r'^[A-G][b#]?\s', text):
                              key = text
                          elif text.endswith('s'):
                              duration = text

              except Exception as e:
                  logging.warning(f"⚠️ DOMからのメタデータ抽出時にエラー: {e}")

              # --- 2. ファイル名の安全な生成 ---
              # タイトルが取れなかった場合は URL から取得
              if title == "Unknown":
                  base_name = url.split('/')[-1].split('?')[0]
                  clean_title = unquote(base_name).replace('.mp3', '')
                  filename = f"{clean_title}.mp3"
              else:
                  # メタデータを組み合わせた整形ファイル名 (例: Trance Kick by axel mizrahi (140bpm F minor 0.4s).mp3)
                  raw_filename = f"{title} by {author} ({bpm} {key} {duration})"
                  clean_filename = re.sub(r'[\\/*?:"<>|]', '', raw_filename)
                  filename = f"{clean_filename}.mp3"

              logging.info(f"📝 抽出されたメタデータ: タイトル='{title}', 作者='{author}', BPM='{bpm}', Key='{key}', Duration='{duration}'")

              # --- 3. バックグラウンド自動ダウンロード ---
              try:
                  async with httpx.AsyncClient() as client:
                      res = await client.get(url, headers={"Referer": "https://samplefocus.com/"})
                      if res.status_code == 200:
                          # ヘッダー検証
                          if res.content.startswith(b'ID3') or res.content.startswith(b'\xff\xfb') or res.content.startswith(b'\xff\xf3'):
                              with open(filename, "wb") as f:
                                  f.write(res.content)
                              logging.info(f"✅ 保存完了: {filename}")
                          else:
                              logging.warning(f"⚠️ 音声以外のファイル構造が検出されたためスキップしました: {filename}")
              except Exception as e:
                  logging.error(f"❌ ダウンロード処理エラー: {e}")

        page.on("response", handle_response)

        logging.info("🌐 Camoufoxで Sample Focus を開きます。自由にブラウズ・試聴してください...")
        await page.goto("https://samplefocus.com/")

        # ユーザーが手動でブラウザを閉じるまで常駐
        await page.wait_for_event("close", timeout=0) # type: ignore

if __name__ == "__main__":
    asyncio.run(main())
"use strict"
import asyncio
import re
import sys
from urllib.parse import quote
import httpx
import logging
from playwright.async_api import (
    async_playwright,
    Request,
    Page,
)
from playwright.async_api._generated import (
    Page
)
import argparse

logging.basicConfig(level=logging.INFO,format='%(asctime)s [%(levelname)s]: %(message)s',datefmt ='%H:%M:%S')

BASE_URL = "https://samplefocus.com"

async def download_mp3_from_search_page(
    page:Page, search_query: str, rank: int = 0
) -> str | None:
    """検索ページ上で直接再生ボタンを押し、MP3 URLを横取りする"""
    mp3_url = None

    # 1. バックグラウンド通信を監視し、CloudFront等の .mp3 リクエストをキャプチャ
    def handle_request(request: Request):
        nonlocal mp3_url
        url: str = request.url
        if ".mp3" in url:
            mp3_url = url
            logging.info(f"MP3 Request Captured: {mp3_url}")

    page.on("request", handle_request)

    encoded_query = quote(search_query)
    search_url = f"{BASE_URL}/samples?search={encoded_query}"
    logging.info(f"🔍 検索ページURL: {search_url}")

    # 検索ページへ移動
    await page.goto(search_url, wait_until="domcontentloaded")

    # 2. カードコンテナ (#samples) の描画を待機
    try:
        await page.wait_for_selector("#samples", timeout=10000)
    except Exception:
        logging.warning("⚠️ #samples の表示待機タイムアウト。続行します...")

    # 3. 最初のサンプルの再生ボタンセレクターを特定してクリック
    # 解析いただいた要素: .sf-card-action .card-action-button
    play_button_selector = "#samples .sf-card-action .card-action-button"

    try:
        logging.info("⏳ 再生ボタンの表示を待機中...")
        play_btn = page.locator(play_button_selector).nth(rank*2) #偶数ボタンはログイン求められるので奇数に
        await play_btn.wait_for(state="attached", timeout=10000)
        await play_btn.wait_for(state="visible", timeout=10000)

        logging.info(
            "▶️ 検索結果上で再生ボタンをクリック（詳細ページへ行かずに通信を発火）..."
        )
        await play_btn.click()

        # クリック後、MP3の通信が発生するまで最大5秒待機
        for _ in range(10):
            if mp3_url:
                break
            await page.wait_for_timeout(500)
        logging.info("⏳ MP3通信を待機中...")

    except Exception as e:
        logging.error(f"⚠️ 検索結果上での再生ボタンクリック失敗: {e}")

    # 4. リクエストから拾えなかった場合、ページ内のHTML/スクリプトからMP3直リンクを正規表現で探す
    if not mp3_url:
        logging.info("👀 ページのHTML/スクリプト内から MP3 URL を探索中...")
        content = await page.content()
        match = re.search(r'https?://[^\s\'"]+\.mp3[^\s\'"]*', content)
        if match:
            mp3_url = match.group(0)

    return mp3_url


def verify_and_save_mp3(data: bytes, output_path: str) -> bool:
    """バイナリの冒頭ヘッダーを確認して MP3 として保存する"""
    if len(data) < 3:
        logging.error("❌ エラー: 受信データが短すぎます。")
        return False

    header_bytes = data[:3]
    hex_str = " ".join([f"{b:02X}" for b in header_bytes])

    logging.info(f"🔬 バイナリ冒頭 (Hex): {hex_str}")

    # 0x49 0x44 0x33 (ID3) の検証
    if header_bytes == b"ID3":
        logging.info("✅ ID3 ヘッダーを確認しました (MP3ファイル)")
    else:
        logging.warning("⚠️ ID3 ヘッダーではありませんが、ファイルを保存します。")

    with open(output_path, "wb") as f:
        f.write(data)

    logging.info(f"💾 ファイルを保存しました: {output_path}")
    return True



async def search_download_sample(keyword: str, output_filename: str = "downloaded.mp3", rank: int = 0, show_browser: bool = False):
    """
    指定されたキーワードで検索し、該当するサンプルをダウンロードする。
    """
    async with async_playwright() as p:
        # Cloudflare対策: Headless Chrome でも各種プロパティを本物のブラウザに偽装
        browser = await p.chromium.launch(
            headless=(not show_browser),
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
            mp3_url = await download_mp3_from_search_page(page, keyword,rank)
            logging.info(f"MP3 URL: {mp3_url}")

            if not mp3_url:
                logging.error("❌ MP3 リソースの URL を取得できませんでした。")
                return

            logging.info(f"🎵 検出された MP3 URL: {mp3_url}")

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
                    logging.error(
                        f"❌ ダウンロード失敗: HTTP ステータス {response.status_code}"
                    )
                    logging.error(f"❌ ダウンロード失敗: {response.status_code}")

        except Exception as e:
            logging.error(f"⚠️ エラーが発生しました: {e}")
        finally:
            await browser.close()

def parse_rank_range(rank_str: str) -> list[int]:
    """
    '0-3' や '0,2,4' や '1' などの文字列を [0, 1, 2, 3] のような整数のリストに変換する
    """
    ranks:set[int] = {0}
    for part in rank_str.split(','):
        part = part.strip()
        if '-' in part:
            start, end = part.split('-', 1)
            ranks.update(range(int(start), int(end) + 1))
        else:
            ranks.add(int(part))
    return sorted(list(ranks))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Sample Focus MP3 Downloader",
        usage="python download_from_query.py -q <search_query> [-r <rank>] [-o <output_filename>]"
    )
    parser.add_argument("-q", "--query", help="検索クエリ (例: 'piano', 'drums')")
    parser.add_argument("-r", "--rank", help="検索結果順位 (例: '0', '0-3', '0,2,5')", default="0")
    parser.add_argument("-o", "--out", help="出力ファイル名 (複数の場合は番号が付与されます)")
    parser.add_argument("-b", "--browser", action="store_true", help="ブラウザを表示して実行")

    args = parser.parse_args()

    if not args.query:
        parser.print_help()
        logging.error("❌ 検索クエリが指定されていません。終了します。")
        sys.exit(1)

    try:
        rank_list = parse_rank_range(args.rank)
    except ValueError:
        logging.error("❌ --rank の指定形式が不正です。(例: '0', '0-3', '0,2,4')")
        sys.exit(1)

    if any(r < 0 for r in rank_list):
        logging.error("❌ 検索結果順位は0以上で指定してください。")
        sys.exit(1)

    logging.info(f"🔍 検索クエリ: {args.query}, 対象順位: {rank_list}")

    # 複数ダウンロード時のファイル名制御
    for r in rank_list:
        if args.out:
            if len(rank_list) > 1:
                # 複数取得時は filename_0.mp3 のように連番を付与
                name_parts = args.out.rsplit('.', 1)
                if len(name_parts) == 2:
                    out_name = f"{name_parts[0]}_{r}.{name_parts[1]}"
                else:
                    out_name = f"{args.out}_{r}"
            else:
                out_name = args.out
        else:
            out_name = f"{args.query}_rank{r}.mp3"

        logging.info(f"\n--- 順位 {r} のダウンロードを開始 ---")
        asyncio.run(search_download_sample(args.query, out_name, r, show_browser=args.browser))
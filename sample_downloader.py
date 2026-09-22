"use strict"
import sys
import re
import requests
from bs4 import (BeautifulSoup)
from playwright.sync_api import (
    sync_playwright,
    Request,
    )

def fetch_sample_metadata_with_playwright(url:str):
    """
    Playwrightでページを読み込み、再生ボタンをピンポイントでクリックしてMP3通信をキャッチする
    """
    captured_audio_url = ""

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )
        page = context.new_page()

        # ネットワークリクエストの監視 (.mp3 を含む URL のみを正確にフィルタリング)
        def handle_request(request: Request):
            nonlocal captured_audio_url
            req_url = request.url
            # 画像 (png, jpg, webp) や波形画像(waveform)を除外し、.mp3 または cloudfront の音声パスをキャッチ
            if ('.mp3' in req_url.lower() or 'samples/sample_files' in req_url) and not any(ext in req_url.lower() for ext in ['.png', '.jpg', '.jpeg', '.webp', 'waveform']):
                captured_audio_url = req_url

        page.on("request", handle_request)

        try:
            page.goto(url, wait_until='networkidle', timeout=30000)
            
            # --- 再生ボタンのピンポイント特定とクリック ---
            # 1. 優先度高: SampleHero コンポーネント内の再生ボタン
            play_btn = page.query_selector('div[id*="SampleHero"] button:has(i.fa-play)')
            
            # 2. 優先度中: アイコン fa-play を持つボタン
            if not play_btn:
                play_btn = page.query_selector('button:has(i.fa-play)')
                
            # 3. 優先度低: aria-label に play が含まれるボタン
            if not play_btn:
                play_btn = page.query_selector('button[aria-label*="Play"], button[aria-label*="play"]')

            if play_btn:
                print("▶️  再生ボタンを検出しました。クリックを実行します...")
                # ボタンクリックと同時に MP3 の通信レスポンスを待機
                try:
                    with page.expect_response(
                        lambda res: ('.mp3' in res.url or 'sample_files' in res.url) and not any(ext in res.url for ext in ['.png', '.jpg', '.webp']),
                        timeout=7000
                    ):
                        play_btn.click()
                except Exception:
                    # タイムアウトした場合も一応数秒待機してキャッチを試みる
                    page.wait_for_timeout(2000)
            else:
                print("⚠️ 再生ボタンが見つかりませんでした。")

            html_content = page.content()

        except Exception as e:
            print(f"⚠️  ページの読み込み/クリック待機中にエラー: {e}")
            html_content = page.content()
        finally:
            browser.close()

    soup = BeautifulSoup(html_content, 'html.parser')

    # 1. タイトルの取得
    title_elem = soup.find('h1')
    title = title_elem.get_text(strip=True) if title_elem else 'Unknown Title'

    # 2. 作者 (Creator) の取得
    author = 'Unknown'
    h5_elem = soup.find('h5')
    if h5_elem and h5_elem.find('a'):
        tg=h5_elem.find('a')
        author = tg.get_text(strip=True) if tg else h5_elem.get_text(strip=True)

    # 3. ul.sample-attrs から各スペック情報（BPM, Key, Duration）の抽出
    bpm = 'N/A'
    key = 'N/A'
    duration = 'N/A'

    attr_items = soup.select('ul.sample-attrs li')
    for item in attr_items:
        text = item.get_text(strip=True)
        if re.search(r'\d+\s*bpm', text, re.IGNORECASE):
            bpm = text
        elif re.search(r'\d+(\.\d+)?s$', text):
            duration = text
        elif item.find('i', class_=re.compile(r'fa-music')) or any(k in text for k in ['major', 'minor', '#', '♭']):
            key = text

    # 4. カテゴリー / タグ（タイプ）の抽出
    category = 'N/A'
    tag_items = soup.select('ul.tag-list li.tag-list-item a')
    if tag_items:
        tags = [t.get_text(strip=True) for t in tag_items]
        category = ", ".join(tags[:3])

    metadata = {
        'title': title,
        'author': author,
        'bpm': bpm,
        'key': key,
        'duration': duration,
        'type': category,
        'audio_url': captured_audio_url
    }

    return metadata

def verify_and_save_audio(response: requests.Response, save_path: str) -> bool:
    """
    ダウンロードしたコンテンツの検証（Content-Typeおよびファイルヘッダー/Magic Numberの確認）
    """
    content_type = response.headers.get('Content-Type', '')
    content = response.content

    print(f"🔍 コンテンツ検証中...")
    print(f"   - HTTP Content-Type: {content_type}")
    print(f"   - データサイズ: {len(content)} bytes")

    # Magic Number（バイナリ先頭バイト）による検証
    is_png = content.startswith(b'\x89PNG\r\n\x1a\n')
    is_mp3 = content.startswith(b'ID3') or content.startswith(b'\xff\xfb') or content.startswith(b'\xff\xf3') or content.startswith(b'\xff\xf2')

    if is_png or 'image/png' in content_type:
        print("❌ エラー: 取得されたファイルは PNG 画像です。音声ファイルのダウンロードに失敗しました。")
        return False
    
    if not is_mp3 and 'audio' not in content_type:
        print("⚠️  警告: MP3の標準シグネチャが確認できませんでしたが、保存を試みます。")

    with open(save_path, 'wb') as f:
        f.write(content)

    print(f"✅ 検証完了: 正しい音声ファイルとして保存されました ({save_path})")
    return True

def confirm_and_download(metadata: dict[str, str], save_path: str | None = None):
    """
    メタデータをターミナルに表示し、ダウンロード前の確認を行う
    """
    print("\n" + "=" * 45)
    print(" 🎵 サンプル メタデータ確認")
    print("=" * 45)
    print(f" タイトル   : {metadata['title']}")
    print(f" 作者       : {metadata['author']}")
    print(f" BPM        : {metadata['bpm']}")
    print(f" キー       : {metadata['key']}")
    print(f" 長さ       : {metadata['duration']}")
    print(f" タグ/タイプ : {metadata['type']}")
    print("=" * 45 + "\n")

    if not metadata['audio_url']:
        print("⚠️  音声ファイルのURLが抽出できませんでした。")
        return

    print(f"🔗 抽出URL: {metadata['audio_url']}")

    # ダウンロード前確認プロンプト
    answer = input("\nこのサンプルをダウンロードしますか？ [y/N]: ").strip().lower()
    
    if answer in ['y', 'yes']:
        if not save_path:
            clean_title = re.sub(r'[\\/*?:"<>|]', "", metadata['title'])
            save_path = f"{clean_title}.mp3"

        print(f"\n⬇️  ダウンロード中: {save_path} ...")
        
        headers = {
            'accept': '*/*',
            'accept-language': 'ja-JP,ja;q=0.9,en-US;q=0.8,en;q=0.7',
            'cache-control': 'no-cache',
            'pragma': 'no-cache',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'referer': 'https://samplefocus.com/'
        }
        
        try:
            res = requests.get(metadata['audio_url'], headers=headers, stream=True)
            res.raise_for_status()
            
            verify_and_save_audio(res, save_path)

        except requests.RequestException as e:
            print(f"❌ ダウンロードに失敗しました: {e}")
    else:
        print("🚫 ダウンロードをキャンセルしました。")

def main():
    if len(sys.argv) > 1:
        target_url = sys.argv[1]
    else:
        target_url = input("Sample FocusのURLを入力してください: ").strip()

    if not target_url:
        print("URLが入力されていません。終了します。")
        return

    print("\n🔍 Playwrightでページをレンダリングしてメタデータを取得中...")
    metadata = fetch_sample_metadata_with_playwright(target_url)

    if metadata:
        confirm_and_download(metadata)

if __name__ == "__main__":
    main()
# Get Sample Focus

[Webページ](https://samplefocus.com/)からサンプル(音声)ファイルを自動的にダウンロードするツール。  

## インストール

```bash
  # 仮想環境の作成
  uv venv

  # 依存関係のインストール
  uv pip install -r requirements.txt
```

## 使い方

```powershell
  # 仮想環境の有効化
  .venv\Scripts\activate
```

### サンプルのURLから直接ダウンロード(--helpでオプションを確認)

```powershell
  uv python download_from_page.py -u "https://samplefocus.com/samples/wet-trance-kick" -o "wet-trance-kick.mp3"
```

### 検索クエリからダウンロード(--helpでオプションを確認)

```powershell
  uv python download_from_query.py -q "wet trance kick" -r "0-2" -o "wet-trance-kick.mp3"
```

### ブラウザを表示してMP3通信をフックし、ダウンロード(Enterで自動ダウンロードのON/OFF切替)

```powershell
  uv python browse_and_hook.py
```

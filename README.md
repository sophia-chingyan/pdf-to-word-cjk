# PDF 轉 Word (CJK)

A private web app that converts digital PDFs into editable Word (`.docx`) files, built for
Traditional Chinese, Simplified Chinese, Japanese (Hiragana, Katakana, Kanji) and Korean, in
both horizontal and vertical (直排 / 縦書き) layouts. It runs as one service on
[Railway](https://railway.com). The interface is in Traditional Chinese.

## What it does

- **Google sign-in** for one allowed email address.
- **Upload** one or more PDFs (up to 40 MB and 100 pages each), then pick the **content settings**
  before converting: language and direction (自動偵測, 繁體中文（橫排／直排）, 簡體中文, 日文, 韓文),
  plus what to do with Japanese furigana (brackets such as `漢字(かんじ)`, or drop).
  - Only horizontal options ticked: every block comes out horizontal. Only vertical: every block
    comes out vertical. Both, or 自動偵測: direction is detected for each block.
  - The last choices are remembered.
- **Background conversion** with a progress bar and Start, Pause, Stop, Retry and Delete.
  Finished pages are cached, so a paused job (or one interrupted by a redeploy) continues from
  the next page.
- **Library**: download the Word file or the original PDF, see the settings, languages and
  directions used and any conversion notes, retry with different settings, and delete one,
  several, or all files.
- **Backup conversion** (optional): a button that sends a PDF to [ConvertAPI](https://www.convertapi.com)
  and keeps the result as a second version. It never runs on its own.

## How the conversion works

`engine/` reads characters, positions and fonts straight from the PDF with PyMuPDF and writes
Word XML with python-docx.

1. **Fix Unicode-encoded fonts.** Fonts with a Unicode CMap encoding (UniGB/UniCNS/UniJIS/UniKS/UniAKR,
   UCS-2, UTF-8, UTF-16 or UTF-32, as ReportLab and other generators write them) are read as the
   Unicode they contain, even when the font's character collection doesn't match the encoding.
2. **Rebuild lines and columns.** PDF tools usually store vertical text as many tiny horizontal
   fragments, so columns are rebuilt from where the characters sit. Sideways Latin letters and
   digits inside vertical text are kept in their column, and so is punctuation that a generator
   (ReportLab) draws shifted into the next cell.
3. **Furigana.** Small kana right beside Kanji (above it in horizontal text, to its right in
   vertical text) is attached to that Kanji and written as `漢字(かんじ)`, or dropped.
4. **Blocks, paragraphs, reading order.** Lines of the same size and direction become blocks;
   indents and short last lines split paragraphs (measured against the usual line length, so
   unjustified text with lines a character or two apart stays together). A recursive XY-cut orders the blocks: columns
   left to right on horizontal pages, right to left on vertical pages. A paragraph that runs on
   into the next column or page is joined back together.
5. **Structure.** Headings come from font size (up to 3 levels), bullet lists are detected,
   ruled tables become Word tables, and images are placed in reading order. Page numbers are left out.
6. **Word output.** Vertical pages become a Word section with text direction `tbRl`. A vertical
   block on a horizontal page goes into a borderless one-cell table with vertical text, so it
   stays editable without floating text boxes. Each run gets an East Asian font and language tag:
   PMingLiU / Microsoft JhengHei (zh-TW), SimSun / Microsoft YaHei (zh-CN), Yu Mincho / Yu Gothic
   (ja), Batang / Malgun Gothic (ko).

Scanned PDFs (no text layer) are out of scope: such pages are placed as images, with a note.

## Deploy on Railway

1. **Google OAuth client.** In [Google Cloud Console](https://console.cloud.google.com/) →
   APIs & Services → Credentials → Create credentials → OAuth client ID → Web application.
   Add the redirect URI `https://<your-domain>/auth/callback` (you can add it after step 3,
   once Railway has generated the domain). Copy the client ID and secret.
2. **New project.** In Railway: New Project → Deploy from GitHub repo → `pdf-to-word-cjk`.
   Railway builds the `Dockerfile` as one service (`railway.json` pins one replica and the
   `/health` check).
3. **Domain.** Service → Settings → Networking → Generate Domain.
4. **Volume.** Right-click the service → Attach Volume, mount path `/data`. The database and all
   files live there, so the library survives redeploys.
5. **Variables.** Service → Variables:

   | Variable | Value |
   | --- | --- |
   | `GOOGLE_CLIENT_ID` | From step 1 |
   | `GOOGLE_CLIENT_SECRET` | From step 1 |
   | `ALLOWED_EMAIL` | The one Google address allowed to sign in |
   | `SESSION_SECRET` | A random string, e.g. `openssl rand -hex 32` |
   | `DATA_DIR` | `/data` (already the default in the Docker image) |
   | `CONVERT_API_KEY` | Optional: ConvertAPI secret, enables the backup button |
   | `APP_BASE_URL` | Optional: set it when you use a custom domain |

   The container exits at boot naming any required variable that is missing (see Deploy Logs).
6. Open the domain, sign in, and upload a PDF.

## Run locally

```bash
pip install -r requirements-dev.txt
DATA_DIR=./data AUTH_DISABLED=1 uvicorn app.main:app --reload --port 8080
```

`AUTH_DISABLED=1` skips Google sign-in for local testing; it is ignored on Railway.

## Tests

```bash
python -m pytest -q
```

The tests build sample PDFs (vertical Japanese with furigana, Traditional Chinese with a heading,
image, table and list, two-column Simplified Chinese, Korean, and a horizontal page with a vertical
block) by rendering Word files with LibreOffice, so `soffice` and CJK fonts must be installed.
CI installs them.

## Known limits

- Furigana detection is a heuristic; ruby set far from its base text stays as ordinary text.
- Complex magazine layouts can still come out in the wrong order; try the backup conversion.
- Fonts with broken encodings extract as wrong characters; the conversion notes flag such pages.
- A horizontal block on a vertical page uses a one-cell table with horizontal text direction;
  check it in Word on your own files.

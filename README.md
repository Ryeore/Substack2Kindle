# Substack2Kindle

Download Substack articles as clean HTML and Kindle-friendly EPUB files. The
HTML is saved first so you can inspect it before or after conversion. Images
are stored beside the HTML and included in the EPUB.

## Requirements

- Python 3.10 or newer
- A network connection to the article and its images
- For Kindle email: a Gmail account with an app password, and the Gmail sender
  address approved in your Amazon **Personal Document Settings**

## Install

In PowerShell, from the project folder:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Open `.env` and configure email delivery:

```dotenv
EMAIL_KINDLE=your_name@kindle.com
EMAIL_PASSWORD=your_gmail_app_password
EMAIL_SENDER=your_gmail_name
SMTP_PORT=587
SMTP_SERVER=smtp.gmail.com
```

`EMAIL_PASSWORD` must be a Google **app password**, not your regular Google
account password. `EMAIL_SENDER` can be your full Gmail address or just the
part before `@gmail.com`. Keep `.env` private; it is excluded from Git.

## Convert articles

Create an EPUB and email it to your Kindle:

```powershell
python app.py https://example.substack.com/p/article
```

Convert several articles in one run:

```powershell
python app.py https://example.substack.com/p/first https://example.substack.com/p/second
```

Only create local files without sending email:

```powershell
python app.py --no-email https://example.substack.com/p/article
```

By default, each article produces:

- `output/<article title>.html` - cleaned article text and formatting for review
- `output/<article title>-assets/` - downloaded article images
- `output/<article title>.epub` - the ebook converted from the saved HTML

Use `--output-dir PATH` to change the output folder. Filenames preserve Polish
letters and spaces. Characters forbidden in Windows filenames (including `?`)
are removed. If an output filename already belongs to another article, a short
URL-based suffix is added.

The HTML contains the article title and body, while excluding embedded
`DigestPostEmbed` article cards. The EPUB opens directly to the article.
Supported downloaded image formats are JPEG, PNG, and GIF; unsupported or
unavailable images are skipped and reported.

## Run the self-hosted webpage

Start the local web app:

```powershell
python web_app.py
```

Open <http://127.0.0.1:8000/> in your browser. Paste up to five Substack
article URLs, one per line, then select whether to email the EPUBs. The page
provides links to review each cleaned HTML file and download its EPUB. Use
`python web_app.py --port 8080` to select another local port.

On Windows, double-click `Start Substack2Kindle.bat` to create the Python
environment, install dependencies on first launch, and open the webpage
automatically. The first launch creates `.env` from `.env.example`; fill in the
Kindle and Gmail settings in Notepad before continuing. Leave the console
window open while using the app, and press Ctrl+C there to stop it.

The web app intentionally listens only on `127.0.0.1` and accepts article
URLs hosted on `substack.com`. Do not expose it directly to your LAN or the
public internet; it has no user login. For remote access, put it behind an
authenticated reverse proxy and add deployment-specific request protections.
Only one conversion request runs at a time.

## Check the output

Open the generated HTML in a browser to review the extracted article before
reading the EPUB. Processing reports each stage and returns a non-zero exit
code if an article or Kindle email fails.

Run the test suite with:

```powershell
python -m unittest -v
```

## Kindle delivery notes

The Kindle address must be enabled for personal document delivery. Amazon may
need to approve the sender email address before accepting documents. Email
delivery was not tested by the unit tests.

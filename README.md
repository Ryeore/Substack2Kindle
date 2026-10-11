# Substack2Kindle

Download Substack articles as clean HTML and Kindle-friendly EPUB files. The
HTML is saved first so you can inspect it before or after conversion. Images
are stored beside the HTML and included in the EPUB.

## Requirements

- Python 3.10 or newer for running from source or building the Windows executable
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

## Run the desktop app

On Windows, double-click `Start Substack2Kindle.bat`. It opens a desktop window
where you can paste up to five Substack article URLs and choose whether to
email the EPUBs to your Kindle. Select **Convert articles** to start, and use
**Open output folder** to find the HTML and EPUB files. Keep the console
window open while converting; close it to stop the app.

The launcher uses the included Python environment when needed. To build a
standalone executable that does not require Python on the target computer,
double-click `Build Substack2Kindle EXE.bat`. After it finishes,
`dist\Substack2Kindle.exe` is the app. The launcher automatically uses that
executable when it exists. The executable keeps `.env` and generated files in
the `dist` folder.

You can also download the ready-to-run Windows executable from the project's
[latest GitHub release](https://github.com/Ryeore/Substack2Kindle/releases/latest).
It is a standalone x64 Windows app; Python does not need to be installed.

On first launch, `.env` is created and opened in Notepad. Add the Kindle
address, Gmail app password, and sender address to enable Kindle delivery;
restart the app after editing settings.

To use only the standalone app, copy `dist\Substack2Kindle.exe` and
`dist\.env.example` to a Windows computer. No Python installation is needed.
The executable creates its own `.env` beside it on first launch and saves
converted files to an `output` folder beside the executable.

The older local web interface is still available with
`python web_app.py`, but it is optional and not used by the desktop launcher.

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

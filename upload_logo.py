"""Upload your own static/logo.png to the configured public R2 bucket."""
from pathlib import Path


def main():
    from configuration import Configuration
    logo = Configuration(Path(__file__).resolve().parent).locations.library/'logo.png'
    if not logo.is_file():
        raise SystemExit('Missing logo.png in the configured library directory. Supply a square PNG you have permission to publish.')
    if logo.stat().st_size > 10*1024*1024 or not logo.read_bytes().startswith(b'\x89PNG\r\n\x1a\n'):
        raise SystemExit('Logo must be a PNG under 10 MiB.')
    from app import r2_enabled, upload_to_r2
    if not r2_enabled():
        raise SystemExit('Complete the R2 settings before uploading artwork.')
    try:
        url = upload_to_r2(logo, 'images/logo.png', 'image/png')
    except Exception:
        raise SystemExit('Logo upload failed. Check R2 credentials, bucket and network access.')
    print('Published logo: '+url)


if __name__ == '__main__':
    main()

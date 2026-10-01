"""Upload the podcast logo to Cloudflare R2. Expects the artwork at static/logo.png. Run once from this folder."""
import os, boto3
from botocore.client import Config
from dotenv import load_dotenv

load_dotenv()

s3 = boto3.client(
    "s3",
    endpoint_url=f"https://{os.getenv('R2_ACCOUNT_ID')}.r2.cloudflarestorage.com",
    aws_access_key_id=os.getenv("R2_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("R2_SECRET_KEY"),
    config=Config(signature_version="s3v4"),
    region_name="auto",
)

logo_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "logo.png")
with open(logo_path, "rb") as f:
    s3.put_object(
        Bucket=os.getenv("R2_BUCKET"),
        Key="images/logo.png",
        Body=f,
        ContentType="image/png",
    )

print("✓ Logo uploaded to R2")
print(f"  URL: {os.getenv('R2_PUBLIC_URL')}/images/logo.png")

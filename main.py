import asyncio
import os
import tempfile
import uuid
from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import yt_dlp
from dotenv import load_dotenv

app = FastAPI()

# Load environment variables from .env file
load_dotenv()

MAX_CONCURRENT_DOWNLOADS = int(os.getenv("MAX_CONCURRENT_DOWNLOADS", "2"))
download_semaphore = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)

# CORS configuration
app.add_middleware(CORSMiddleware,
    allow_origins=[os.getenv("ALLOWED_ORIGIN")],  # Adjust this to your needs
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/download")
async def download_video(url: str = Query(...), format: str = Query("best")):
    try:
        # Extract metadata without blocking the event loop.
        def extract_info():
            with yt_dlp.YoutubeDL({'quiet': True, 'skip_download': True}) as ydl:
                return ydl.extract_info(url, download=False)

        info = await asyncio.to_thread(extract_info)
        title = info.get("title", "video").replace("/", "-").replace("\\", "-")
        extension = "mp4"
        filename = f"{title}.{extension}"

        async with download_semaphore:
            download_dir = tempfile.mkdtemp(prefix="ydl_")
            uid = uuid.uuid4().hex[:8]
            output_template = os.path.join(download_dir, f"{uid}.%(ext)s")

            ydl_opts = {
                'format': format,
                'outtmpl': output_template,
                'quiet': True,
                'merge_output_format': 'mp4',
            }

            def download():
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    return ydl.download([url])

            await asyncio.to_thread(download)

            actual_file_path = None
            for f in os.listdir(download_dir):
                if f.startswith(uid):
                    actual_file_path = os.path.join(download_dir, f)
                    break

            if not actual_file_path or not os.path.exists(actual_file_path):
                raise HTTPException(status_code=500, detail="Download failed or file not found.")

            def iterfile():
                try:
                    with open(actual_file_path, "rb") as f:
                        yield from f
                finally:
                    try:
                        os.unlink(actual_file_path)
                    except OSError:
                        pass
                    try:
                        os.rmdir(download_dir)
                    except OSError:
                        pass

            return StreamingResponse(
                iterfile(),
                media_type="application/octet-stream",
                headers={"Content-Disposition": f'attachment; filename="{filename}"'}
            )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error during download: {str(e)}")

@app.get("/")
async def root():
    return {"message": "Welcome to the Social Media Video Downloader API. Use /download?url=<video_url>&format=<video_format> to download videos."}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
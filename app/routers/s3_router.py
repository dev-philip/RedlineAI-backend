# app/routers/s3_router.py
from typing import Optional
from fastapi import APIRouter, Query, UploadFile, File, HTTPException, Depends
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from app.services.s3_service import S3Service
from app.dependencies import get_s3_service

router = APIRouter()

@router.post("/upload")
async def upload_to_s3(
    file: UploadFile = File(...),
    s3: S3Service = Depends(get_s3_service),
):
    try:
        result = await s3.upload_fileobj(file=file, filename=file.filename, content_type=file.content_type)
    except ValueError as ve:
        raise HTTPException(status_code=413, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"S3 error: {e}")
    return JSONResponse(result)


@router.get("/files/presign")
def presign_file_url(
    key: str = Query(..., description="S3 object key returned by /upload"),
    expires_in: int = Query(300, ge=1, le=3600),
    download: bool = Query(False, description="If true, force download"),
    filename: Optional[str] = Query(None, description="Optional filename for download dialog"),
    response_content_type: Optional[str] = Query(None, description="Override Content-Type if needed"),
    s3: S3Service = Depends(get_s3_service),
):
    try:
        url = s3.presign_get_url(key, expires_in, download, filename, response_content_type)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"url": url, "expires_in": expires_in, "key": key}


@router.get("/files/{key:path}")
def redirect_to_file(
    key: str,
    expires_in: int = Query(300, ge=1, le=3600),
    download: bool = Query(False),
    filename: Optional[str] = Query(None),
    s3: S3Service = Depends(get_s3_service),
):
    try:
        url = s3.presign_get_url(key, expires_in, download, filename)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return RedirectResponse(url, status_code=307)


@router.get("/files/stream/{key:path}")
def stream_file(
    key: str,
    s3: S3Service = Depends(get_s3_service),
):
    try:
        obj = s3.get_object(key)
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Not found or access denied: {e}")

    media_type = obj.get("ContentType", "application/octet-stream")
    content_len = obj.get("ContentLength")
    headers = {}
    if content_len is not None:
        headers["Content-Length"] = str(content_len)

    return StreamingResponse(s3.iter_body(obj["Body"]), media_type=media_type, headers=headers)

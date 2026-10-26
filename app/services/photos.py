"""Photo handling: always re-encode to a small square JPEG so storage stays tiny and EXIF/GPS is dropped."""
import io

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_UPLOAD_BYTES = 6 * 1024 * 1024
SIZE = 240


def process_photo(file_storage) -> bytes | None:
    """Return a ~10-25 KB JPEG, None if no file was sent, or raise ValueError for a bad file."""
    if file_storage is None or not getattr(file_storage, "filename", ""):
        return None
    raw = file_storage.read(MAX_UPLOAD_BYTES + 1)
    if not raw:
        return None
    if len(raw) > MAX_UPLOAD_BYTES:
        raise ValueError("That photo file is too large.")
    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise ValueError("That file is not a valid photo.") from None
    img = ImageOps.exif_transpose(img).convert("RGB")
    img = ImageOps.fit(img, (SIZE, SIZE), Image.LANCZOS)
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=70, optimize=True)  # re-encoding strips EXIF/location data
    return out.getvalue()

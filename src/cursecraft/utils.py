import zipfile, os, requests, base64, hashlib
from typing import Optional, List, Tuple, Dict, Any
from tqdm import tqdm
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from concurrent.futures import ThreadPoolExecutor, as_completed

universal_headers = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.3 Safari/605.1.15",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://www.google.com/",
    "Connection": "keep-alive",
}


class HashVerificationError(Exception):
    pass


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(
        (
            ConnectionError,
            requests.exceptions.Timeout,
            requests.exceptions.HTTPError,
            requests.exceptions.RequestException,
        )
    ),
    reraise=True,
)
def request(
    method: str,
    url: str,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, Any]] = None,
    json: Optional[Dict[str, Any]] = None,
) -> requests.Response:
    response = requests.request(
        method=method.upper(),
        url=url,
        headers=headers,
        params=params,
        json=json,
    )
    response.raise_for_status()
    return response


def get(
    url: str,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, Any]] = None,
    json: Optional[Dict[str, Any]] = None,
) -> requests.Response:
    return request(
        method="GET",
        url=url,
        headers=headers,
        params=params,
        json=json,
    )


def post(
    url: str,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, Any]] = None,
    json: Optional[Dict[str, Any]] = None,
) -> requests.Response:
    return request(
        method="POST",
        url=url,
        headers=headers,
        params=params,
        json=json,
    )


def unzip_file(
    zip_path: str, extract_to: str = ".", password: Optional[str] = None
) -> bool:
    os.makedirs(extract_to, exist_ok=True)

    with zipfile.ZipFile(zip_path, "r") as zip_ref:
        pwd_bytes = password.encode("utf-8") if password else None
        zip_ref.extractall(path=extract_to, pwd=pwd_bytes)

    return True


def get_main_class(jar_path: str):
    with zipfile.ZipFile(jar_path, "r") as zip_ref:
        for file_name in zip_ref.namelist():
            if file_name == "META-INF/MANIFEST.MF":
                manifest_content = zip_ref.read(file_name).decode("utf-8")
                break
    for line in manifest_content.splitlines():
        if line.startswith("Main-Class:"):
            return line.split(":", 1)[1].strip()
    return None


def resolve_maven_coord(coord: str) -> str:
    extension = "jar"
    if "@" in coord:
        coord_body, extension = coord.rsplit("@", 1)
        if "@" in coord_body:
            raise ValueError(f"Invalid maven coord: {coord}")
        parts = coord_body.split(":")
    else:
        parts = coord.split(":")

    if len(parts) < 3:
        raise ValueError(f"Invalid maven coord: {coord}")

    group = parts[0]
    artifact = parts[1]
    version = parts[2]
    classifier = parts[3] if len(parts) > 3 else None

    if classifier and "@" in classifier:
        classifier, extension = classifier.split("@", 1)
    group_path = group.replace(".", "/")
    filename = f"{artifact}-{version}"

    if classifier:
        filename += f"-{classifier}"
    filename += f".{extension}"
    return f"{group_path}/{artifact}/{version}/{filename}"


def get_minecraft_dir_path() -> str:
    home_path = os.path.expanduser("~")
    if os.name == "nt":
        appdata = os.getenv("APPDATA")
        minecraft_dir_path = (
            os.path.join(appdata, ".minecraft")
            if appdata
            else os.path.join(home_path, ".minecraft")
        )
    elif os.name == "posix":
        if os.path.exists(
            os.path.join(home_path, "Library", "Application Support", "minecraft")
        ):
            minecraft_dir_path = os.path.join(
                home_path, "Library", "Application Support", "minecraft"
            )
        else:
            minecraft_dir_path = os.path.join(home_path, ".minecraft")
    else:
        minecraft_dir_path = os.path.join(home_path, ".minecraft")
    return minecraft_dir_path


def calculate_file_hash(file_path: str, hash_algo: str):
    hash_func = hashlib.new(hash_algo)
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            hash_func.update(chunk)
    return hash_func.hexdigest()


def hash_verify(file_path: str, expected_hash: str, hash_algo: str):
    expected_hash = expected_hash.lower().strip()
    file_hash = calculate_file_hash(file_path, hash_algo)
    if file_hash == expected_hash:
        return True
    return False


def get_image_base64(image_url: str) -> str:
    try:
        response = requests.get(image_url, headers=universal_headers, timeout=10)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"Failed to fetch image: {e}")
        return None

    content_type = response.headers.get("Content-Type", "")
    if ";" in content_type:
        content_type = content_type.split(";")[0].strip()

    if not content_type.startswith("image/"):
        if image_url.lower().endswith(".jpg") or image_url.lower().endswith(".jpeg"):
            content_type = "image/jpeg"
        elif image_url.lower().endswith(".webp"):
            content_type = "image/webp"
        elif image_url.lower().endswith(".gif"):
            content_type = "image/gif"
        else:
            content_type = "image/png"

    base64_data = base64.b64encode(response.content).decode("utf-8")
    return f"data:{content_type};base64,{base64_data}"


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(
        (
            ConnectionError,
            requests.exceptions.Timeout,
            requests.exceptions.HTTPError,
            requests.exceptions.RequestException,
            HashVerificationError,
        )
    ),
    reraise=True,
    before_sleep=lambda retry_state: print(
        f"Attempt {retry_state.attempt_number} failed: {retry_state.outcome.exception()}. Retrying..."
    ),
)
def _do_download_job(
    url: str,
    file_path: str,
    block_size: int,
    headers: dict,
    expected_hash: str | None,
    hash_algo: str,
):
    try:
        with requests.get(url=url, stream=True, headers=headers) as response:
            response.raise_for_status()

            total_size = int(response.headers.get("content-length", 0))
            with open(file_path, "wb") as f:
                with tqdm(
                    total=total_size,
                    unit="B",
                    unit_scale=True,
                    desc=os.path.basename(file_path),
                ) as pbar:
                    for chunk in response.iter_content(chunk_size=block_size):
                        if chunk:
                            f.write(chunk)
                            pbar.update(len(chunk))

        if expected_hash is not None:
            if not hash_verify(file_path, expected_hash, hash_algo):
                if os.path.exists(file_path):
                    os.remove(file_path)
                raise HashVerificationError(
                    f"Hash mismatch for {os.path.basename(file_path)}. Expected: {expected_hash}"
                )

    except Exception as e:
        print(f"Unknown error occured when downloading: {e}")
        if os.path.exists(file_path):
            os.remove(file_path)
        raise


def single_download(
    url: str,
    file_name: str,
    dest_path: Optional[str] = None,
    block_size: int = 8192,
    expected_hash: Optional[str] = None,
    hash_algo: str = "sha256",
) -> bool:

    if dest_path is None:
        home_path = os.path.expanduser("~")
        dest_path = os.path.join(home_path, "Downloads")
    os.makedirs(dest_path, exist_ok=True)
    full_path = os.path.join(dest_path, file_name)

    if os.path.exists(full_path):
        if expected_hash:
            if hash_verify(full_path, expected_hash, hash_algo):
                return True
            os.remove(full_path)

    root, ext = os.path.splitext(full_path)
    temp_path = root + ext + ".tmp"

    try:
        _do_download_job(
            url=url,
            file_path=temp_path,
            block_size=block_size,
            headers=universal_headers,
            expected_hash=expected_hash,
            hash_algo=hash_algo,
        )
        os.replace(temp_path, full_path)
        return True
    except Exception as e:
        print(f"Download failed permanently after retries: {file_name}: {e}")
        if os.path.exists(temp_path):
            os.remove(temp_path)
        return False


def batch_download(
    files: List[Tuple[str, str] | Tuple[str, str, str, str]],
    dest_path: str | None = None,
    block_size: int = 8192,
    max_workers: int = 5,
) -> List[bool]:
    results = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future2file = {}
        for item in files:
            args = (
                (item[1], item[0], dest_path, block_size)
                if len(item) == 2
                else (
                    (item[1], item[0], dest_path, block_size, item[2], item[3])
                    if len(item) == 4
                    else None
                )
            )
            future2file[executor.submit(single_download, *args)] = item[0]

        for future in as_completed(future2file):
            file_name = future2file[future]
            try:
                success = future.result()
                results[file_name] = success
            except Exception as exc:
                print(f"Unexpected error downloading {file_name}: {exc}")
                results[file_name] = False

    return [results[item[0]] for item in files if item[0] in results]

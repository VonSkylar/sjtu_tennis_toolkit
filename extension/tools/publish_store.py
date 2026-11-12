"""Check or submit an existing Chrome Web Store listing using its v2 API."""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zipfile import BadZipFile, ZipFile


API = "https://chromewebstore.googleapis.com"
UPLOAD_PENDING = {"IN_PROGRESS", "UPLOAD_IN_PROGRESS"}
ACTIVE_SUBMISSION = {"PENDING_REVIEW", "STAGED"}


def request(path, token, *, data=None, headers=None):
    request_headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    request_headers.update(headers or {})
    try:
        with urlopen(Request(API + path, data=data, headers=request_headers), timeout=30) as response:
            return json.load(response)
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        try:
            message = json.loads(detail)["error"]["message"]
        except (KeyError, TypeError, ValueError):
            message = error.reason
        raise RuntimeError(f"Google API HTTP {error.code}: {message}") from None
    except (TimeoutError, URLError) as error:
        raise RuntimeError(f"Google API request failed: {error}. Check the dashboard before retrying.") from None


def version_key(version):
    parts = version.split(".")
    if not 1 <= len(parts) <= 4 or any(not re.fullmatch(r"0|[1-9][0-9]{0,4}", part) for part in parts):
        raise ValueError(f"Invalid extension version: {version!r}")
    numbers = tuple(map(int, parts))
    if max(numbers) > 65535 or not any(numbers):
        raise ValueError(f"Invalid extension version: {version!r}")
    return numbers + (0,) * (4 - len(numbers))


def listing_status(resource, token):
    status = request(f"/v2/{resource}:fetchStatus", token)
    if status.get("name") != resource:
        raise RuntimeError("Google returned a different listing than the one configured.")
    return status


def versions(status, field):
    revision = status.get(field, {})
    return [channel["crxVersion"] for channel in revision.get("distributionChannels", []) if channel.get("crxVersion")]


def wait_for_upload(resource, token):
    for _ in range(30):
        time.sleep(5)
        state = listing_status(resource, token).get("lastAsyncUploadState")
        if state == "SUCCEEDED":
            return
        if state not in UPLOAD_PENDING | {None, "NOT_FOUND"}:
            raise RuntimeError(f"Chrome Web Store upload did not succeed: {state}")
    raise RuntimeError("Chrome Web Store is still processing the upload. Check Package in the dashboard before retrying.")


def submit(resource, token, archive, publish_type):
    with ZipFile(archive) as package:
        manifest = json.loads(package.read("manifest.json"))
    version = manifest["version"]
    version_number = version_key(version)
    status = listing_status(resource, token)
    published = versions(status, "publishedItemRevisionStatus")
    if published and version_number <= max(map(version_key, published)):
        raise RuntimeError(f"Version {version} must be newer than the published version(s): {', '.join(published)}")
    pending = status.get("submittedItemRevisionStatus", {}).get("state")
    if pending in ACTIVE_SUBMISSION:
        raise RuntimeError(f"A submission already exists ({pending}). Check the dashboard before uploading another version.")
    if status.get("lastAsyncUploadState") in UPLOAD_PENDING:
        raise RuntimeError("The store is already processing an upload. Check the dashboard before retrying.")

    upload = request(
        f"/upload/v2/{resource}:upload", token, data=archive.read_bytes(),
        headers={"Content-Type": "application/zip", "X-Goog-Upload-Protocol": "raw",
                 "X-Goog-Upload-File-Name": archive.name},
    )
    uploaded_version = upload.get("crxVersion")
    if upload.get("name") != resource or (uploaded_version and uploaded_version != version):
        raise RuntimeError("The upload response did not match the selected listing and ZIP version.")
    upload_state = upload.get("uploadState")
    if upload_state in UPLOAD_PENDING:
        wait_for_upload(resource, token)
    elif upload_state != "SUCCEEDED":
        raise RuntimeError(f"Chrome Web Store upload did not succeed: {upload_state}")
    print(f"Upload accepted for {version}.", flush=True)

    result = request(
        f"/v2/{resource}:publish", token,
        data=json.dumps({"publishType": publish_type}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    if result.get("name") != resource or result.get("state") not in {"PENDING_REVIEW", "STAGED", "PUBLISHED"}:
        raise RuntimeError(f"Submission status could not be confirmed: {result.get('state')}. Check the dashboard.")
    print(f"Chrome Web Store version {version}: {result['state']} ({publish_type}).")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check", help="read the listing status")
    publish = commands.add_parser("submit", help="upload the ZIP and submit for review")
    publish.add_argument("archive", type=Path)
    publish.add_argument("--publish-type", choices=("DEFAULT_PUBLISH", "STAGED_PUBLISH"), required=True)
    args = parser.parse_args()

    publisher = os.environ.get("CWS_PUBLISHER_ID", "")
    item = os.environ.get("CWS_ITEM_ID", "")
    token = os.environ.get("CWS_ACCESS_TOKEN", "")
    publisher_format = r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}"
    if not re.fullmatch(publisher_format, publisher) or not re.fullmatch(r"[a-p]{32}", item) or not token:
        parser.error("Set the publisher UUID, Chrome extension ID, and Google access token.")
    resource = f"publishers/{publisher}/items/{item}"
    try:
        if args.command == "check":
            status = listing_status(resource, token)
            published = versions(status, "publishedItemRevisionStatus")
            print(f"Connected to Chrome Web Store listing {item}. Published: {', '.join(published) or 'none'}.")
        else:
            submit(resource, token, args.archive, args.publish_type)
    except (BadZipFile, KeyError, OSError, RuntimeError, ValueError) as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

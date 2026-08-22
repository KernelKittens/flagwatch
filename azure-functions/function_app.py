from __future__ import annotations

import logging
import os

import azure.functions as func
from azure.core.exceptions import ResourceNotFoundError
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient, ContentSettings

from flagwatch.cli import build_sync_service
from flagwatch.cloud_sync import BlobStore, CloudSnapshotService
from flagwatch.config import Settings
from flagwatch.storage import Database

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)


class AzureBlobStore:
    def __init__(self, account_url: str, container: str) -> None:
        credential = DefaultAzureCredential()
        service = BlobServiceClient(account_url=account_url, credential=credential)
        self.container = service.get_container_client(container)

    def download(self, name: str) -> bytes | None:
        try:
            return self.container.download_blob(name).readall()
        except ResourceNotFoundError:
            return None

    def upload(self, name: str, value: bytes, *, content_type: str) -> None:
        self.container.upload_blob(
            name,
            value,
            overwrite=True,
            content_settings=ContentSettings(content_type=content_type),
        )

    def delete(self, name: str) -> None:
        self.container.delete_blob(name, delete_snapshots="include")


def blob_store() -> BlobStore:
    return AzureBlobStore(
        account_url=os.environ["FLAGWATCH_STORAGE_ACCOUNT_URL"],
        container=os.environ.get("FLAGWATCH_STORAGE_CONTAINER", "flagwatch"),
    )


def run_sync(database: Database) -> object:
    settings = Settings(
        database_path=database.path,
        send_enabled=False,
        ai_enabled=False,
    )
    report = build_sync_service(settings, queue_notifications=False).run()
    if report.analyzed and report.verified_policies == 0:
        logging.warning(
            "Flagwatch refresh completed with zero current verified AI policies: "
            "%d analyzed, %d unverified",
            report.analyzed,
            report.unverified_policies,
        )
    return report


@app.route(route="events", methods=["GET"])
def events(req: func.HttpRequest) -> func.HttpResponse:
    del req
    payload = blob_store().download(CloudSnapshotService.public_blob)
    if payload is None:
        return func.HttpResponse(
            '{"error":"Calendar data is not ready yet."}',
            status_code=503,
            mimetype="application/json",
            headers={"Cache-Control": "no-store", "Retry-After": "300"},
        )
    return func.HttpResponse(
        payload,
        status_code=200,
        mimetype="application/json",
        headers={"Cache-Control": "public, max-age=300, stale-if-error=86400"},
    )


@app.timer_trigger(
    schedule="0 0 */6 * * *",
    arg_name="timer",
    run_on_startup=False,
    use_monitor=True,
)
def refresh_snapshot(timer: func.TimerRequest) -> None:
    del timer
    CloudSnapshotService(blob_store(), run_sync).refresh()

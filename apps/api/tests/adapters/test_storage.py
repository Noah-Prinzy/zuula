"""S3 through boto3, with botocore's Stubber in place of the network."""

import io

import boto3
import pytest
from botocore.response import StreamingBody
from botocore.stub import Stubber

from app.adapters.storage import S3ObjectStorage


@pytest.fixture
def s3():
    client = boto3.client(
        "s3",
        region_name="us-east-1",
        endpoint_url="https://r2.example.com",
        aws_access_key_id="id",
        aws_secret_access_key="secret",
    )
    with Stubber(client) as stubber:
        yield S3ObjectStorage(client=client, bucket="zuula-media"), stubber
        stubber.assert_no_pending_responses()


async def test_put_get_delete(s3):
    storage, stubber = s3
    stubber.add_response(
        "put_object",
        {},
        {
            "Bucket": "zuula-media",
            "Key": "submissions/a/original",
            "Body": b"img",
            "ContentType": "image/png",
        },
    )
    stubber.add_response(
        "get_object",
        {"Body": StreamingBody(io.BytesIO(b"img"), 3)},
        {"Bucket": "zuula-media", "Key": "submissions/a/original"},
    )
    stubber.add_response(
        "delete_object", {}, {"Bucket": "zuula-media", "Key": "submissions/a/original"}
    )

    ref = await storage.put(key="submissions/a/original", data=b"img", content_type="image/png")
    assert ref == "s3://zuula-media/submissions/a/original"
    assert await storage.get(key="submissions/a/original") == b"img"
    await storage.delete(key="submissions/a/original")


async def test_errors_propagate(s3):
    storage, stubber = s3
    stubber.add_client_error("get_object", service_error_code="NoSuchKey", http_status_code=404)
    with pytest.raises(Exception, match="NoSuchKey"):
        await storage.get(key="missing")


async def test_check_asks_for_the_bucket(s3):
    storage, stubber = s3
    stubber.add_response("head_bucket", {}, {"Bucket": "zuula-media"})
    await storage.check()
    stubber.add_client_error("head_bucket", service_error_code="403", http_status_code=403)
    with pytest.raises(Exception, match="403"):
        await storage.check()


def test_a_custom_endpoint_uses_path_style(adapter_env):
    # Supabase Storage only answers path-style requests (…/storage/v1/s3/<bucket>/<key>).
    adapter_env(
        S3_ENDPOINT_URL="https://abc.supabase.co/storage/v1/s3",
        S3_ACCESS_KEY_ID="id",
        S3_SECRET_ACCESS_KEY="secret",
        S3_BUCKET="zuula-documents",
        S3_REGION="eu-west-1",
    )
    client = S3ObjectStorage.from_settings()._client
    assert client.meta.config.s3["addressing_style"] == "path"
    url = client.generate_presigned_url(
        "get_object", Params={"Bucket": "zuula-documents", "Key": "k"}
    )
    assert url.startswith("https://abc.supabase.co/storage/v1/s3/zuula-documents/k")

import os
import boto3
from botocore.exceptions import ClientError
from typing import Dict, List, Optional, BinaryIO, Union
from dotenv import load_dotenv
import mimetypes
import uuid
from fastapi import UploadFile

# Load environment variables
load_dotenv()


class S3Handler:
    """
    Handles AWS S3 operations for file storage, including uploads,
    downloads, presigned URLs, and listing/deleting files.
    """

    def __init__(self):
        """Initialize S3 client using environment variables."""
        self.aws_access_key_id = os.getenv("AWS_ACCESS_KEY_ID")
        self.aws_secret_access_key = os.getenv("AWS_SECRET_ACCESS_KEY")
        self.bucket_name = os.getenv("AWS_BUCKET_NAME")
        self.region = os.getenv("AWS_REGION", "us-east-1")

        # Initialize S3 client
        self.s3_client = boto3.client(
            "s3",
            aws_access_key_id=self.aws_access_key_id,
            aws_secret_access_key=self.aws_secret_access_key,
            region_name=self.region,
        )

    def upload_file(
        self,
        file_obj: Union[BinaryIO, UploadFile],
        s3_key: Optional[str] = None,
        content_type: Optional[str] = None,
        metadata: Optional[Dict] = None,
    ) -> Dict:
        """
        Upload a file to S3 bucket.

        Args:
            file_obj: File object or FastAPI UploadFile to upload
            s3_key: S3 object key (path within bucket). If None, generates a UUID-based key.
            content_type: MIME type of the file. If None, guesses from filename.
            metadata: Optional metadata to attach to the S3 object

        Returns:
            Dict containing the uploaded file information:
            {
                "key": S3 object key,
                "url": Public URL for the file,
                "bucket": S3 bucket name
            }
        """
        # Generate a unique key if none provided
        if s3_key is None:
            file_extension = ""
            if hasattr(file_obj, "filename"):  # For UploadFile
                _, file_extension = os.path.splitext(file_obj.filename)
            s3_key = f"{uuid.uuid4()}{file_extension}"

        # Determine content type if not provided
        if content_type is None and hasattr(file_obj, "filename"):
            content_type, _ = mimetypes.guess_type(file_obj.filename)

        # Set default content type if still None
        if content_type is None:
            content_type = "application/octet-stream"

        # Prepare upload parameters
        upload_args = {
            "Bucket": self.bucket_name,
            "Key": s3_key,
            "ContentType": content_type,
        }

        # Add metadata if provided
        if metadata:
            # Convert all metadata values to strings as required by S3
            str_metadata = {k: str(v) for k, v in metadata.items()}
            upload_args["Metadata"] = str_metadata

        # Handle different types of file objects
        if hasattr(file_obj, "file"):  # For UploadFile from FastAPI
            self.s3_client.upload_fileobj(file_obj.file, **upload_args)
        elif hasattr(file_obj, "read"):  # For file-like objects
            self.s3_client.upload_fileobj(file_obj, **upload_args)
        else:
            raise ValueError("Unsupported file object type")

        # Return file information
        return {
            "key": s3_key,
            "url": f"https://{self.bucket_name}.s3.{self.region}.amazonaws.com/{s3_key}",
            "bucket": self.bucket_name,
        }

    def generate_presigned_url(self, s3_key: str, expiration: int = 3600) -> str:
        """
        Generate a presigned URL for an S3 object to allow temporary access.

        Args:
            s3_key: S3 object key
            expiration: URL expiration time in seconds (default: 1 hour)

        Returns:
            Presigned URL string
        """
        try:
            presigned_url = self.s3_client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket_name, "Key": s3_key},
                ExpiresIn=expiration,
            )
            return presigned_url
        except ClientError as e:
            print(f"Error generating presigned URL: {e}")
            raise

    def list_files(self, prefix: str = "") -> List[Dict]:
        """
        List files in an S3 bucket directory (prefix).

        Args:
            prefix: Directory prefix to list (e.g., "module-pdfs/")

        Returns:
            List of dicts containing file information:
            [
                {
                    "key": S3 object key,
                    "size": File size in bytes,
                    "last_modified": Last modified timestamp,
                    "url": Public URL for the file
                },
                ...
            ]
        """
        try:
            response = self.s3_client.list_objects_v2(
                Bucket=self.bucket_name, Prefix=prefix
            )

            if "Contents" not in response:
                return []

            files = []
            for item in response["Contents"]:
                files.append(
                    {
                        "key": item["Key"],
                        "size": item["Size"],
                        "last_modified": item["LastModified"].isoformat(),
                        "url": f"https://{self.bucket_name}.s3.{self.region}.amazonaws.com/{item['Key']}",
                    }
                )

            return files
        except ClientError as e:
            print(f"Error listing files: {e}")
            raise

    def delete_file(self, s3_key: str) -> bool:
        """
        Delete a file from S3.

        Args:
            s3_key: S3 object key to delete

        Returns:
            True if deletion was successful, False otherwise
        """
        try:
            self.s3_client.delete_object(Bucket=self.bucket_name, Key=s3_key)
            return True
        except ClientError as e:
            print(f"Error deleting file: {e}")
            return False

    def download_file(self, s3_key: str, destination_path: str) -> bool:
        """
        Download a file from S3 to a local path.

        Args:
            s3_key: S3 object key to download
            destination_path: Local file path to save the downloaded file

        Returns:
            True if download was successful, False otherwise
        """
        try:
            self.s3_client.download_file(
                Bucket=self.bucket_name, Key=s3_key, Filename=destination_path
            )
            return True
        except ClientError as e:
            print(f"Error downloading file: {e}")
            return False

    def get_object_metadata(self, s3_key: str) -> Dict:
        """
        Get metadata for an S3 object.

        Args:
            s3_key: S3 object key

        Returns:
            Dict containing object metadata
        """
        try:
            response = self.s3_client.head_object(Bucket=self.bucket_name, Key=s3_key)
            return {
                "content_type": response.get("ContentType"),
                "content_length": response.get("ContentLength"),
                "last_modified": (
                    response.get("LastModified").isoformat()
                    if response.get("LastModified")
                    else None
                ),
                "metadata": response.get("Metadata", {}),
            }
        except ClientError as e:
            print(f"Error getting object metadata: {e}")
            raise

    def file_exists(self, s3_key: str) -> bool:
        """
        Check if a file exists in S3.

        Args:
            s3_key: S3 object key to check

        Returns:
            True if the file exists, False otherwise
        """
        try:
            self.s3_client.head_object(Bucket=self.bucket_name, Key=s3_key)
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] == "404":
                return False
            else:
                print(f"Error checking file existence: {e}")
                raise

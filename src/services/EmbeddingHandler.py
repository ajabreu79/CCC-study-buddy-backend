import os
import tempfile
from typing import List, Dict, Any, Optional, Union
from dataclasses import dataclass
from datetime import datetime

from langchain.document_loaders import PyPDFLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings
from langchain_pinecone import PineconeVectorStore
from pinecone.control.pinecone import Pinecone
from pinecone import Index, ServerlessSpec
from pydantic import SecretStr

from src.services.S3Handler import S3Handler
from firebase_config import db
from src.constants import (
    MODULE_RESOURCES,
    PROCESSING_STATUS,
    MODIFIED_AT,
    PROCESSED_AT,
    ERROR_MESSAGE,
    CHUNK_COUNT,
)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
pc = Pinecone(api_key=PINECONE_API_KEY)
embeddings = OpenAIEmbeddings(api_key=SecretStr(OPENAI_API_KEY))

index_name = "eaton-modules"

if index_name not in pc.list_indexes().names():
    pc.create_index(
        name=index_name,
        dimension=1536,
        metric="cosine",
        spec=ServerlessSpec(cloud="aws", region="us-east-1"),
    )


@dataclass
class EmbeddingResult:
    success: bool
    chunk_count: int = 0
    error: str = ""
    namespace: str = ""


class EmbeddingHandler:
    """Handles embedding operations for RAG implementation"""

    def __init__(self, default_index_name: str = "eaton-modules"):
        self.s3_handler = S3Handler()
        self.default_index_name = default_index_name
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000, chunk_overlap=200, separators=["\n\n", "\n", ". ", " ", ""]
        )

    def get_index(self, index_name: Optional[str] = None) -> Index:
        """Get the Pinecone index object

        Args:
            index_name: The name of the index to use, defaults to the instance default

        Returns:
            The Pinecone index object
        """
        index_name = index_name or self.default_index_name
        return pc.Index(index_name)

    def chunk_documents(
        self,
        documents: List[Document],
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
    ) -> List[Document]:
        """Split documents into smaller chunks for better embedding and retrieval

        Args:
            documents: The documents to split
            chunk_size: The size of each chunk in characters
            chunk_overlap: The overlap between chunks in characters

        Returns:
            A list of chunked documents
        """
        # Configure the splitter with provided parameters
        self.text_splitter.chunk_size = chunk_size
        self.text_splitter.chunk_overlap = chunk_overlap

        return self.text_splitter.split_documents(documents)

    def embed_documents(
        self,
        documents: List[Document],
        index_name: Optional[str] = None,
        namespace: str = "default",
    ) -> EmbeddingResult:
        """Embed documents and store in Pinecone

        Args:
            documents: List of documents to embed
            index_name: The name of the Pinecone index
            namespace: The namespace within the index

        Returns:
            EmbeddingResult with status and metadata
        """
        try:
            index_name = index_name or self.default_index_name

            # Create embeddings and store in Pinecone
            PineconeVectorStore.from_documents(
                documents,
                embeddings,
                index_name=index_name,
                namespace=namespace,
            )

            return EmbeddingResult(
                success=True, chunk_count=len(documents), namespace=namespace
            )
        except Exception as e:
            return EmbeddingResult(success=False, error=str(e))

    def embed_s3_pdf(
        self,
        s3_key: str,
        resource_id: str,
        agent_id: str,
        index_name: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
    ) -> EmbeddingResult:
        """Embed a PDF stored in S3 directly

        Args:
            s3_key: The S3 key of the PDF file
            resource_id: The ID of the resource in Firestore
            agent_id: The ID of the module/agent
            index_name: The name of the Pinecone index
            metadata: Additional metadata to include with embeddings
            chunk_size: Size of each chunk in characters
            chunk_overlap: Overlap between chunks in characters

        Returns:
            EmbeddingResult with status and metadata
        """
        # Update processing status in Firestore
        resource_ref = db.collection(MODULE_RESOURCES).document(resource_id)
        resource_ref.update(
            {
                PROCESSING_STATUS: "processing",
                MODIFIED_AT: datetime.utcnow(),
            }
        )

        try:
            # Create a temporary file for the PDF
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
            temp_file.close()

            # Download from S3
            self.s3_handler.download_file(s3_key, temp_file.name)

            # Create namespace for this resource
            namespace = f"module_{agent_id}_resource_{resource_id}"

            # Load PDF
            loader = PyPDFLoader(temp_file.name)
            documents = loader.load()

            # Apply chunking
            chunked_docs = self.chunk_documents(
                documents, chunk_size=chunk_size, chunk_overlap=chunk_overlap
            )

            # Add metadata to documents
            base_metadata = {
                "resource_id": resource_id,
                "agent_id": agent_id,
                "file_name": os.path.basename(s3_key),
                "file_type": "pdf",
            }

            # Add additional metadata if provided
            if metadata:
                base_metadata.update(metadata)

            # Add chunk-specific metadata
            for i, doc in enumerate(chunked_docs):
                # Ensure metadata exists
                if not hasattr(doc, "metadata"):
                    doc.metadata = {}

                # Add base metadata
                doc.metadata.update(base_metadata)

                # Add chunk-specific metadata
                doc.metadata["chunk_id"] = i

            # Embed documents
            result = self.embed_documents(
                chunked_docs,
                index_name=index_name or self.default_index_name,
                namespace=namespace,
            )

            # Clean up temp file
            os.unlink(temp_file.name)

            # Update Firestore with status
            if result.success:
                resource_ref.update(
                    {
                        PROCESSING_STATUS: "complete",
                        PROCESSED_AT: datetime.utcnow(),
                        CHUNK_COUNT: result.chunk_count,
                        MODIFIED_AT: datetime.utcnow(),
                    }
                )
            else:
                resource_ref.update(
                    {
                        PROCESSING_STATUS: "error",
                        ERROR_MESSAGE: result.error,
                        MODIFIED_AT: datetime.utcnow(),
                    }
                )

            return result

        except Exception as e:
            # Update Firestore with error
            resource_ref.update(
                {
                    PROCESSING_STATUS: "error",
                    ERROR_MESSAGE: str(e),
                    MODIFIED_AT: datetime.utcnow(),
                }
            )

            return EmbeddingResult(success=False, error=str(e))

    def update_embeddings(
        self,
        resource_id: str,
        index_name: Optional[str] = None,
    ) -> EmbeddingResult:
        """Update embeddings for an existing resource

        Args:
            resource_id: The ID of the resource to update
            index_name: The name of the Pinecone index

        Returns:
            EmbeddingResult with status and metadata
        """
        # Get resource data from Firestore
        resource_ref = db.collection(MODULE_RESOURCES).document(resource_id)
        resource_doc = resource_ref.get()

        if not resource_doc.exists:
            return EmbeddingResult(
                success=False, error=f"Resource {resource_id} not found"
            )

        resource_data = resource_doc.to_dict()
        s3_key = resource_data.get("s3_key")
        agent_id = resource_data.get("agent_id")

        if not s3_key or not agent_id:
            return EmbeddingResult(
                success=False, error="Missing required fields in resource data"
            )

        # Create namespace for this resource
        namespace = f"module_{agent_id}_resource_{resource_id}"

        # Delete existing embeddings from Pinecone
        try:
            index = self.get_index(index_name)
            index.delete(namespace=namespace, delete_all=True)
        except Exception as e:
            print(f"Warning: Failed to delete existing embeddings: {str(e)}")

        # Embed PDF again
        metadata = {
            "original_filename": resource_data.get("original_filename"),
            "uploader_id": resource_data.get("uploader_id"),
            "update_timestamp": datetime.utcnow().isoformat(),
        }

        return self.embed_s3_pdf(
            s3_key=s3_key,
            resource_id=resource_id,
            agent_id=agent_id,
            index_name=index_name,
            metadata=metadata,
        )


# For backwards compatibility
def embed_file(
    index_name: str,
    namespace: str,
    file_path: str,
    file_id: str,
    file_name: str,
    file_type: str,
    agent_id: str = "NA",
    workspace_id: str = "NA",
    documents: Optional[List[Document]] = None,
) -> bool:
    """Embed the file and put the embeddings into the Pinecone index.

    Legacy function kept for compatibility. For new code, use the EmbeddingHandler class.

    Args:
        index_name: The name of the Pinecone index.
        namespace: The namespace of the Pinecone index.
        file_path: The path of the file to be embedded.
        file_id: The ID of the file.
        file_name: The name of the file.
        file_type: The type of the file.
        agent_id: The ID of the agent. Optional.
        workspace_id: The ID of the workspace. Optional.
        documents: Optional pre-processed documents list. If provided, these will be used instead of loading from file_path.

    Returns:
        True if the embedding is successful, False otherwise.
    """
    if file_type == "pdf":
        if documents:
            # Use provided documents (pre-processed)
            pages = documents
        else:
            # Load from file path
            pages = pdf_loader(file_path)

        # Add metadata to the pages
        for page in pages:
            if not hasattr(page, "metadata"):
                page.metadata = {}
            page.metadata.update(
                {
                    "file_id": file_id,
                    "file_type": file_type,
                    "file_path": file_path,
                    "agent_id": agent_id,
                    "workspace_id": workspace_id,
                    "file_name": file_name,
                }
            )

        # Create embeddings
        try:
            PineconeVectorStore.from_documents(
                pages,
                embeddings,
                index_name=index_name,
                namespace=namespace,
            )
            return True
        except Exception as e:
            print(f"Error embedding documents: {str(e)}")
            return False

    print("Unsupported file type")
    return False


def pdf_loader(file_path: str) -> list[Document]:
    """Load the PDF file and embed the contents into the Pinecone index.

    Args:
        file_path: The path of the PDF file.

    Returns:
        A list of Document objects containing the embedded contents of the PDF file.
    """
    loader = PyPDFLoader(file_path)
    return loader.load_and_split()

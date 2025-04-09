import os
import tempfile
from typing import Dict, List, Optional, Any
import datetime
import time

from langchain.document_loaders import PyPDFLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_core.documents import Document

from src.services.S3Handler import S3Handler
from src.services.EmbeddingHandler import embed_file
from firebase_config import db
from src.constants import (
    MODULE_RESOURCES,
    PROCESSING_STATUS,
    PROCESSED_AT,
    CHUNK_COUNT,
    ERROR_MESSAGE,
    MODIFIED_AT,
)


class PDFProcessor:
    """Service for processing PDF files for the RAG system"""

    def __init__(self, pinecone_index: str = "eaton-modules"):
        """Initialize the PDF processor

        Args:
            pinecone_index: Name of the Pinecone index to use
        """
        self.s3_handler = S3Handler()
        self.pinecone_index = pinecone_index
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=200,
            separators=["\n\n", "\n", ". ", " ", ""],
        )

    def extract_text_from_pdf(self, file_path: str) -> List[Document]:
        """Extract text from a PDF file

        Args:
            file_path: Path to the PDF file

        Returns:
            List of Document objects with extracted text and page metadata
        """
        try:
            loader = PyPDFLoader(file_path)
            return loader.load()
        except Exception as e:
            print(f"Error extracting text from PDF: {str(e)}")
            raise

    def chunk_text(
        self,
        documents: List[Document],
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
    ) -> List[Document]:
        """Split documents into chunks for embedding

        Args:
            documents: List of documents to chunk
            chunk_size: Size of each chunk in characters
            chunk_overlap: Overlap between chunks in characters

        Returns:
            List of chunked Document objects
        """
        # Configure the splitter with provided parameters
        self.text_splitter.chunk_size = chunk_size
        self.text_splitter.chunk_overlap = chunk_overlap

        # Split the documents
        return self.text_splitter.split_documents(documents)

    def process_s3_pdf_for_embedding(
        self,
        s3_key: str,
        resource_id: str,
        agent_id: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Process a PDF stored in S3 for embedding

        Args:
            s3_key: S3 key of the PDF file
            resource_id: ID of the resource in Firestore
            agent_id: ID of the module/agent
            metadata: Additional metadata for the embeddings

        Returns:
            Dict with processing results
        """
        # Update processing status in Firestore
        resource_ref = db.collection(MODULE_RESOURCES).document(resource_id)
        resource_ref.update(
            {
                PROCESSING_STATUS: "processing",
                MODIFIED_AT: datetime.datetime.utcnow(),
            }
        )

        try:
            # Create a temporary file for the PDF
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
            temp_file.close()

            # Download the PDF from S3
            self.s3_handler.download_file(s3_key, temp_file.name)

            # Extract text from the PDF
            documents = self.extract_text_from_pdf(temp_file.name)

            # Chunk the text
            chunked_docs = self.chunk_text(documents)

            # Prepare namespace for this specific resource
            namespace = f"module_{agent_id}"

            # Add chunk_id to metadata
            for i, doc in enumerate(chunked_docs):
                if not hasattr(doc, "metadata"):
                    doc.metadata = {}

                # Base metadata
                doc.metadata.update(
                    {
                        "resource_id": resource_id,
                        "agent_id": agent_id,
                        "chunk_id": i,
                    }
                )

                # Add additional metadata if provided
                if metadata:
                    doc.metadata.update(metadata)

            # Use the existing embed_file function but with our processed chunks
            # Since we've already processed the chunks ourselves, we're just
            # leveraging the embedding and storage part of the function
            success = embed_file(
                index_name=self.pinecone_index,
                namespace=namespace,
                file_path=temp_file.name,  # Original file path still needed for some metadata
                file_id=resource_id,
                file_name=(
                    metadata.get("original_filename", os.path.basename(s3_key))
                    if metadata
                    else os.path.basename(s3_key)
                ),
                file_type="pdf",
                agent_id=agent_id,
            )

            # Clean up the temporary file
            os.unlink(temp_file.name)

            if success:
                # Update Firestore with processing complete
                resource_ref.update(
                    {
                        PROCESSING_STATUS: "complete",
                        PROCESSED_AT: datetime.datetime.utcnow(),
                        CHUNK_COUNT: len(chunked_docs),
                        MODIFIED_AT: datetime.datetime.utcnow(),
                    }
                )
                return {
                    "success": True,
                    "chunk_count": len(chunked_docs),
                    "resource_id": resource_id,
                    "agent_id": agent_id,
                }
            else:
                raise Exception("Embedding failed")

        except Exception as e:
            print(f"Error processing PDF: {str(e)}")
            # Update Firestore with error status
            resource_ref.update(
                {
                    PROCESSING_STATUS: "error",
                    ERROR_MESSAGE: str(e),
                    MODIFIED_AT: datetime.datetime.utcnow(),
                }
            )
            return {
                "success": False,
                "error": str(e),
                "resource_id": resource_id,
                "agent_id": agent_id,
            }

    def reprocess_resource(self, resource_id: str) -> Dict[str, Any]:
        """Reprocess an existing resource

        Args:
            resource_id: ID of the resource to reprocess

        Returns:
            Dict with processing results
        """
        # Get the resource data
        resource_ref = db.collection(MODULE_RESOURCES).document(resource_id)
        resource_doc = resource_ref.get()

        if not resource_doc.exists:
            return {
                "success": False,
                "error": "Resource not found",
                "resource_id": resource_id,
            }

        resource_data = resource_doc.to_dict()
        s3_key = resource_data.get("s3_key")
        agent_id = resource_data.get("agent_id")

        if not s3_key or not agent_id:
            return {
                "success": False,
                "error": "Resource missing required fields",
                "resource_id": resource_id,
            }

        # Reprocess the resource
        return self.process_s3_pdf_for_embedding(
            s3_key=s3_key,
            resource_id=resource_id,
            agent_id=agent_id,
            metadata={
                "original_filename": resource_data.get("original_filename"),
                "uploader_id": resource_data.get("uploader_id"),
            },
        )
